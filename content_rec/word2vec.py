#!/usr/bin/Python
# -*- coding: utf-8 -*-
import random
import jieba
import numpy as np
import re
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import matplotlib.pyplot as plt

from torch.autograd import Variable
from collections import Counter
from tqdm import tqdm
from sklearn.manifold import TSNE


class SkipGram(nn.Module):
    embedding_dir = './data/embedding.dict'

    def __init__(self, word_size, emb_dim):
        """
        :param word_size: total word number
        :param emb_dim: Feature dimensions of each word, generally 50～500
        """
        super(SkipGram, self).__init__()
        self.word_size = word_size
        self.emb_dim = emb_dim
        self.u_embed = nn.Embedding(word_size, emb_dim, sparse=True)
        self.v_embed = nn.Embedding(word_size, emb_dim, sparse=True)
        self._init_emb()

    def _init_emb(self):
        """
        Initialization of embedding,
        u_embed obeys normal distribution
        v_embed value is 0
        :return:
        """
        init_range = 0.5 / self.emb_dim
        self.u_embed.weight.data.uniform_(-init_range, init_range)
        self.v_embed.weight.data.uniform_(-0, 0)

    def forward(self, pos_u, pos_v, neg_v):
        """
        Forward propagation and negative sampling is considered
        :param pos_u: The id of the center word
        :param pos_v: The id of the neighbor word，a positive sample
        :param neg_v: The id of the neighbor word，a negative sample
        :return: loss
        """
        emb_u = self.u_embed(pos_u)
        emb_v = self.v_embed(pos_v)
        score = F.logsigmoid(torch.sum(torch.mul(emb_u, emb_v).squeeze()))
        neg_emb_v = self.v_embed(neg_v)
        neg_score = torch.sum(
            torch.bmm(neg_emb_v, emb_u.unsqueeze(2)).squeeze())
        neg_score = F.logsigmoid(-1 * neg_score)
        return -1 * (torch.sum(score) + torch.sum(neg_score))

    def save_embedding(self, int_to_word):
        """
        save word embedding
        :param int_to_word: Convert word_id to word
        :return:
        """
        embed = self.u_embed.weight.data.numpy()
        with open(self.embedding_dir, 'w', encoding='utf-8') as f:
            for id, w in int_to_word.items():
                e = embed[id]
                e = ' '.join(map(lambda x: str(x), e))
                f.write('%s %s\n' % (str(w), e))

    def dispaly(self):
        """
        With Tsne dimensionless display
        :return:
        """
        viz_words = 200  # Display 200 words
        tsne = TSNE()
        embed = self.u_embed.weight.data.numpy()
        embed_tsne = tsne.fit_transform(embed[:viz_words, :])
        fig, ax = plt.subplots(figsize=(14, 14))
        plt.xlabel(u'x')
        plt.ylabel(u'y')
        for idx in range(viz_words):
            plt.scatter(*embed_tsne[idx, :], color='steelblue')
            plt.annotate(int_to_vocab[idx],
                         (embed_tsne[idx, 0], embed_tsne[idx, 1]), alpha=0.7)
        plt.show()


class Word2Vec(object):

    def __init__(self, data, emb_dim=100, batch_size=16, window_size=5,
                 epochs=1, lr=0.025, min_count=5):
        """
        initializer
        :param data:
        :param emb_dim: Feature dimensions of each word, generally 50～500. Google uses 300.
        :param batch_size:
        :param window_size:
        :param epochs:
        :param lr: learining rate
        :param min_count: Minimum count of occurrences per word
        """
        self.train_data = self._subsampling(data, min_count)
        self.emb_dim = emb_dim
        self.word_size = len(int_to_vocab)
        self.batch_size = batch_size
        self.window_size = window_size
        self.epochs = epochs
        self.lr = lr
        self.skip_gram = SkipGram(self.word_size, self.emb_dim)
        self.optimizer = optim.SGD(self.skip_gram.parameters(), lr=self.lr)

    def _subsampling(self, data, min_count):
        """
        Participle, mapping, secondary sampling
        :param data:
        :param min_count:
        :return: the numerical form of data
        """
        new_data = re.sub(r'[^\u4e00-\u9fa5]', '', data)  # Filtering punctuation, character changes, etc
        words = jieba.cut(new_data)
        word_list = [word for word in words]
        word_counts = Counter(word_list)
        trim_word = [word for word in word_list if
                     word_counts[word] > min_count]  # throw the low-frequency word
        sorted_vocab = sorted(word_counts, key=word_counts.get, reverse=True)
        # Common words convert Numbers
        global int_to_vocab, vocab_to_int
        int_to_vocab = {i: word for i, word in enumerate(sorted_vocab)}
        vocab_to_int = {word: i for i, word in int_to_vocab.items()}
        # secondary sampling
        thr = 1e-5
        total_count = len(trim_word)
        freqs = {word: count / total_count for word, count in
                 word_counts.items()}  # 计算频度
        p_drop = {word: 1 - np.sqrt(thr / freqs[word]) for word in
                  word_counts}  # 计算丢弃概率
        train_words = [word for word in trim_word if
                       random.random() < p_drop[word]]  # 丢弃
        int_words = [vocab_to_int[word] for word in train_words]
        return int_words

    def _get_target(self, words, idx):
        """
        Get the target from the window
        :param words: words list
        :param idx: Current index value
        :return:
        """
        R = np.random.randint(1, self.window_size + 1)
        start = idx - R if (idx - R) > 0 else 0
        stop = idx + R
        target_words = set(words[start:idx] + words[idx + 1:stop + 1])
        return list(target_words)

    def _get_batches(self):
        """
        offer batches
        :yield: pos_u, pos_v, neg_v
        """
        n_batches = len(self.train_data) // self.batch_size
        words = self.train_data[: n_batches * self.batch_size]  # 防止出现不够用
        for idx in range(0, len(words), self.batch_size):
            x, y, z = [], [], []
            batch = words[idx: idx + self.batch_size]
            for i in range(len(batch)):
                batch_x = batch[i]
                batch_y = self._get_target(batch, i)
                x.extend([batch_x] * len(batch_y))
                y.extend(batch_y)
            z = np.random.choice(self.train_data,
                                 size=(len(y), self.window_size))
            yield x, y, z

    def train(self):
        """
        Training data, save the embedding, and show some words
        :return:
        """
        process_bar = tqdm(range(self.epochs))
        for i in process_bar:
            batches = self._get_batches()
            for pos_u, pos_v, neg_v in batches:
                pos_u = Variable(torch.LongTensor(pos_u))
                pos_v = Variable(torch.LongTensor(pos_v))
                neg_v = Variable(torch.LongTensor(neg_v))
                self.optimizer.zero_grad()
                loss = self.skip_gram.forward(pos_u, pos_v, neg_v)
                loss.backward()
                self.optimizer.step()
                process_bar.set_description("Loss: %0.4f, lr: %0.6f" % (
                    loss.data.item(), self.optimizer.param_groups[0]['lr']))
                if i * self.batch_size % 100000 == 0:
                    lr = self.lr * (1.0 - 1.0 * i / self.epochs)
                    for param_group in self.optimizer.param_groups:
                        param_group['lr'] = lr
        self.skip_gram.save_embedding(int_to_vocab)
        self.skip_gram.dispaly()


if __name__ == "__main__":
    corpus_dir = './data/corpus_xueqiu.txt'  # Corpus, each line represents an article
    corpus_dir = './data/idf_test.txt'  # test article, one line
    text = open(corpus_dir, 'rb').read().decode('utf-8')
    wv = Word2Vec(text, epochs=1)
    wv.train()
