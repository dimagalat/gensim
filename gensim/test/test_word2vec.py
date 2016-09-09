#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2010 Radim Rehurek <radimrehurek@seznam.cz>
# Licensed under the GNU LGPL v2.1 - http://www.gnu.org/licenses/lgpl.html

"""
Automated tests for checking transformation algorithms (the models package).
"""


import logging
import unittest
import os
import tempfile
import itertools
import bz2

import numpy

from gensim import utils, matutils
from gensim.utils import check_output
from subprocess import PIPE
from gensim.models import word2vec, keyedvectors
from testfixtures import log_capture

try:
    from pyemd import emd
    PYEMD_EXT = True
except ImportError:
    PYEMD_EXT = False

module_path = os.path.dirname(__file__) # needed because sample data files are located in the same folder
datapath = lambda fname: os.path.join(module_path, 'test_data', fname)


class LeeCorpus(object):
    def __iter__(self):
        with open(datapath('lee_background.cor')) as f:
            for line in f:
                yield utils.simple_preprocess(line)

list_corpus = list(LeeCorpus())

sentences = [
    ['human', 'interface', 'computer'],
    ['survey', 'user', 'computer', 'system', 'response', 'time'],
    ['eps', 'user', 'interface', 'system'],
    ['system', 'human', 'system', 'eps'],
    ['user', 'response', 'time'],
    ['trees'],
    ['graph', 'trees'],
    ['graph', 'minors', 'trees'],
    ['graph', 'minors', 'survey']
]

def testfile():
    # temporary data will be stored to this file
    return os.path.join(tempfile.gettempdir(), 'gensim_word2vec.tst')


def _rule(word, count, min_count):
    if word == "human":
        return utils.RULE_DISCARD  # throw out
    else:
        return utils.RULE_DEFAULT  # apply default rule, i.e. min_count


class TestWord2VecModel(unittest.TestCase):
    def testPersistence(self):
        """Test storing/loading the entire model."""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.save(testfile())
        self.models_equal(model, word2vec.Word2Vec.load(testfile()))
        #  test persistence of the KeyedVectors of a model
        kv = model.kv
        kv.save(testfile())
        loaded_kv = keyedvectors.KeyedVectors.load(testfile())
        self.assertTrue(numpy.allclose(kv.syn0, loaded_kv.syn0))
        self.assertEqual(len(kv.vocab), len(loaded_kv.vocab))

    def testPersistenceWithConstructorRule(self):
        """Test storing/loading the entire model with a vocab trimming rule passed in the constructor."""
        model = word2vec.Word2Vec(sentences, min_count=1, trim_rule=_rule)
        model.save(testfile())
        self.models_equal(model, word2vec.Word2Vec.load(testfile()))

    def testRuleWithMinCount(self):
        """Test that returning RULE_DEFAULT from trim_rule triggers min_count."""
        model = word2vec.Word2Vec(sentences + [["occurs_only_once"]], min_count=2, trim_rule=_rule)
        self.assertTrue("human" not in model.vocab)
        self.assertTrue("occurs_only_once" not in model.vocab)
        self.assertTrue("interface" in model.vocab)

    def testRule(self):
        """Test applying vocab trim_rule to build_vocab instead of constructor."""
        model = word2vec.Word2Vec(min_count=1)
        model.build_vocab(sentences, trim_rule=_rule)
        self.assertTrue("human" not in model.vocab)

    def testLambdaRule(self):
        """Test that lambda trim_rule works."""
        rule = lambda word, count, min_count: utils.RULE_DISCARD if word == "human" else utils.RULE_DEFAULT
        model = word2vec.Word2Vec(sentences, min_count=1, trim_rule=rule)
        self.assertTrue("human" not in model.vocab)

    def testSyn0NormNotSaved(self):
        """Test syn0norm isn't saved in model file"""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        model.save(testfile())
        loaded_model = word2vec.Word2Vec.load(testfile())
        self.assertTrue(loaded_model.kv.syn0norm is None)

        kv = model.kv
        kv.save(testfile())
        loaded_kv = keyedvectors.KeyedVectors.load(testfile())
        self.assertTrue(loaded_kv.syn0norm is None)

    def testLoadPreKeyedVectorModel(self):
        """Test loading pre-KeyedVectors word2vec model"""

        # Model stored in one file
        model = word2vec.Word2Vec.load(datapath('word2vec_pre_kv'))
        self.assertTrue(model.syn0.shape == (len(model.kv.vocab), model.vector_size))
        self.assertTrue(model.syn1neg.shape == (len(model.kv.vocab), model.vector_size))

        # Model stored in multiple files
        model = word2vec.Word2Vec.load(datapath('word2vec_pre_kv_sep'))
        self.assertTrue(model.syn0.shape == (len(model.kv.vocab), model.vector_size))
        self.assertTrue(model.syn1neg.shape == (len(model.kv.vocab), model.vector_size))

    def testLoadPreKeyedVectorModelCFormat(self):
        """Test loading pre-KeyedVectors word2vec model saved in word2vec format"""
        model = word2vec.Word2Vec.load_word2vec_format(datapath('word2vec_pre_kv_c'))
        self.assertTrue(model.syn0.shape[0] == len(model.kv.vocab))

    def testPersistenceWord2VecFormat(self):
        """Test storing/loading the entire model in word2vec format."""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        model.save_word2vec_format(testfile(), binary=True)
        binary_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=True)
        binary_model.init_sims(replace=False)
        self.assertTrue(numpy.allclose(model['human'], binary_model['human']))
        norm_only_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=True)
        norm_only_model.init_sims(replace=True)
        self.assertFalse(numpy.allclose(model['human'], norm_only_model['human']))
        self.assertTrue(numpy.allclose(model.syn0norm[model.vocab['human'].index], norm_only_model['human']))
        limited_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=True, limit=3)
        self.assertEquals(len(limited_model.syn0), 3)
        half_precision_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=True, datatype=numpy.float16)
        self.assertEquals(binary_model.syn0.nbytes, half_precision_model.syn0.nbytes * 2)

    def testTooShortBinaryWord2VecFormat(self):
        tfile = testfile()
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        model.save_word2vec_format(tfile, binary=True)
        f = open(tfile, 'r+b')
        f.write(b'13')  # write wrong (too-long) vector count
        f.close()
        self.assertRaises(EOFError, word2vec.Word2Vec.load_word2vec_format, tfile, binary=True)

    def testTooShortTextWord2VecFormat(self):
        tfile = testfile()
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        model.save_word2vec_format(tfile, binary=False)
        f = open(tfile, 'r+b')
        f.write(b'13')  # write wrong (too-long) vector count
        f.close()
        self.assertRaises(EOFError, word2vec.Word2Vec.load_word2vec_format, tfile, binary=False)

    def testPersistenceWord2VecFormatNonBinary(self):
        """Test storing/loading the entire model in word2vec non-binary format."""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        model.save_word2vec_format(testfile(), binary=False)
        text_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=False)
        text_model.init_sims(False)
        self.assertTrue(numpy.allclose(model['human'], text_model['human'], atol=1e-6))
        norm_only_model = word2vec.Word2Vec.load_word2vec_format(testfile(), binary=False)
        norm_only_model.init_sims(True)
        self.assertFalse(numpy.allclose(model['human'], norm_only_model['human'], atol=1e-6))
        self.assertTrue(numpy.allclose(model.syn0norm[model.vocab['human'].index], norm_only_model['human'], atol=1e-4))

    def testPersistenceWord2VecFormatWithVocab(self):
        """Test storing/loading the entire model and vocabulary in word2vec format."""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        testvocab = os.path.join(tempfile.gettempdir(), 'gensim_word2vec.vocab')
        model.save_word2vec_format(testfile(), testvocab, binary=True)
        binary_model_with_vocab = word2vec.Word2Vec.load_word2vec_format(testfile(), testvocab, binary=True)
        self.assertEqual(model.vocab['human'].count, binary_model_with_vocab.vocab['human'].count)

    def testPersistenceWord2VecFormatCombinationWithStandardPersistence(self):
        """Test storing/loading the entire model and vocabulary in word2vec format chained with
         saving and loading via `save` and `load` methods`."""
        model = word2vec.Word2Vec(sentences, min_count=1)
        model.init_sims()
        testvocab = os.path.join(tempfile.gettempdir(), 'gensim_word2vec.vocab')
        model.save_word2vec_format(testfile(), testvocab, binary=True)
        binary_model_with_vocab = word2vec.Word2Vec.load_word2vec_format(testfile(), testvocab, binary=True)
        binary_model_with_vocab.save(testfile())
        binary_model_with_vocab = word2vec.Word2Vec.load(testfile())
        self.assertEqual(model.vocab['human'].count, binary_model_with_vocab.vocab['human'].count)

    def testLargeMmap(self):
        """Test storing/loading the entire model."""
        model = word2vec.Word2Vec(sentences, min_count=1)

        # test storing the internal arrays into separate files
        model.save(testfile(), sep_limit=0)
        self.models_equal(model, word2vec.Word2Vec.load(testfile()))

        # make sure mmaping the arrays back works, too
        self.models_equal(model, word2vec.Word2Vec.load(testfile(), mmap='r'))

    def testVocab(self):
        """Test word2vec vocabulary building."""
        corpus = LeeCorpus()
        total_words = sum(len(sentence) for sentence in corpus)

        # try vocab building explicitly, using all words
        model = word2vec.Word2Vec(min_count=1, hs=1, negative=0)
        model.build_vocab(corpus)
        self.assertTrue(len(model.vocab) == 6981)
        # with min_count=1, we're not throwing away anything, so make sure the word counts add up to be the entire corpus
        self.assertEqual(sum(v.count for v in model.vocab.values()), total_words)
        # make sure the binary codes are correct
        numpy.allclose(model.vocab['the'].code, [1, 1, 0, 0])

        # test building vocab with default params
        model = word2vec.Word2Vec(hs=1, negative=0)
        model.build_vocab(corpus)
        self.assertTrue(len(model.vocab) == 1750)
        numpy.allclose(model.vocab['the'].code, [1, 1, 1, 0])

        # no input => "RuntimeError: you must first build vocabulary before training the model"
        self.assertRaises(RuntimeError, word2vec.Word2Vec, [])

        # input not empty, but rather completely filtered out
        self.assertRaises(RuntimeError, word2vec.Word2Vec, corpus, min_count=total_words+1)

    def testTraining(self):
        """Test word2vec training."""
        # build vocabulary, don't train yet
        model = word2vec.Word2Vec(size=2, min_count=1, hs=1, negative=0)
        model.build_vocab(sentences)

        self.assertTrue(model.syn0.shape == (len(model.vocab), 2))
        self.assertTrue(model.syn1.shape == (len(model.vocab), 2))

        model.train(sentences)
        sims = model.most_similar('graph', topn=10)
        # self.assertTrue(sims[0][0] == 'trees', sims)  # most similar

        # test querying for "most similar" by vector
        graph_vector = model.syn0norm[model.vocab['graph'].index]
        sims2 = model.most_similar(positive=[graph_vector], topn=11)
        sims2 = [(w, sim) for w, sim in sims2 if w != 'graph']  # ignore 'graph' itself
        self.assertEqual(sims, sims2)

        # build vocab and train in one step; must be the same as above
        model2 = word2vec.Word2Vec(sentences, size=2, min_count=1, hs=1, negative=0)
        self.models_equal(model, model2)

    def testScoring(self):
        """Test word2vec scoring."""
        model = word2vec.Word2Vec(sentences, size=2, min_count=1, hs=1, negative=0)

        # just score and make sure they exist
        scores = model.score(sentences, len(sentences))
        self.assertEqual(len(scores), len(sentences))

    def testLocking(self):
        """Test word2vec training doesn't change locked vectors."""
        corpus = LeeCorpus()
        # build vocabulary, don't train yet
        for sg in range(2):  # test both cbow and sg
            model = word2vec.Word2Vec(size=4, hs=1, negative=5, min_count=1, sg=sg, window=5)
            model.build_vocab(corpus)

            # remember two vectors
            locked0 = numpy.copy(model.syn0[0])
            unlocked1 = numpy.copy(model.syn0[1])
            # lock the vector in slot 0 against change
            model.syn0_lockf[0] = 0.0

            model.train(corpus)
            self.assertFalse((unlocked1 == model.syn0[1]).all())  # unlocked vector should vary
            self.assertTrue((locked0 == model.syn0[0]).all())  # locked vector should not vary

    def model_sanity(self, model, train=True):
        """Even tiny models trained on LeeCorpus should pass these sanity checks"""
        # run extra before/after training tests if train=True
        if train:
            model.build_vocab(list_corpus)
            orig0 = numpy.copy(model.syn0[0])
            model.train(list_corpus)
            self.assertFalse((orig0 == model.syn0[1]).all())  # vector should vary after training
        sims = model.most_similar('war', topn=len(model.index2word))
        t_rank = [word for word, score in sims].index('terrorism')
        # in >200 calibration runs w/ calling parameters, 'terrorism' in 50-most_sim for 'war'
        self.assertLess(t_rank, 50)
        war_vec = model['war']
        sims2 = model.most_similar([war_vec], topn=51)
        self.assertTrue('war' in [word for word, score in sims2])
        self.assertTrue('terrorism' in [word for word, score in sims2])

    def test_sg_hs(self):
        """Test skipgram w/ hierarchical softmax"""
        model = word2vec.Word2Vec(sg=1, window=4, hs=1, negative=0, min_count=5, iter=10, workers=2)
        self.model_sanity(model)

    def test_sg_neg(self):
        """Test skipgram w/ negative sampling"""
        model = word2vec.Word2Vec(sg=1, window=4, hs=0, negative=15, min_count=5, iter=10, workers=2)
        self.model_sanity(model)

    def test_cbow_hs(self):
        """Test CBOW w/ hierarchical softmax"""
        model = word2vec.Word2Vec(sg=0, cbow_mean=1, alpha=0.05, window=8, hs=1, negative=0,
                                  min_count=5, iter=10, workers=2, batch_words=1000)
        self.model_sanity(model)

    def test_cbow_neg(self):
        """Test CBOW w/ negative sampling"""
        model = word2vec.Word2Vec(sg=0, cbow_mean=1, alpha=0.05, window=5, hs=0, negative=15,
                                  min_count=5, iter=10, workers=2, sample=0)
        self.model_sanity(model)

    def testTrainingCbow(self):
        """Test CBOW word2vec training."""
        # to test training, make the corpus larger by repeating its sentences over and over
        # build vocabulary, don't train yet
        model = word2vec.Word2Vec(size=2, min_count=1, sg=0, hs=1, negative=0)
        model.build_vocab(sentences)
        self.assertTrue(model.syn0.shape == (len(model.vocab), 2))
        self.assertTrue(model.syn1.shape == (len(model.vocab), 2))

        model.train(sentences)
        sims = model.most_similar('graph', topn=10)
        # self.assertTrue(sims[0][0] == 'trees', sims)  # most similar

        # test querying for "most similar" by vector
        graph_vector = model.syn0norm[model.vocab['graph'].index]
        sims2 = model.most_similar(positive=[graph_vector], topn=11)
        sims2 = [(w, sim) for w, sim in sims2 if w != 'graph']  # ignore 'graph' itself
        self.assertEqual(sims, sims2)

        # build vocab and train in one step; must be the same as above
        model2 = word2vec.Word2Vec(sentences, size=2, min_count=1, sg=0, hs=1, negative=0)
        self.models_equal(model, model2)

    def testTrainingSgNegative(self):
        """Test skip-gram (negative sampling) word2vec training."""
        # to test training, make the corpus larger by repeating its sentences over and over
        # build vocabulary, don't train yet
        model = word2vec.Word2Vec(size=2, min_count=1, hs=0, negative=2)
        model.build_vocab(sentences)
        self.assertTrue(model.syn0.shape == (len(model.vocab), 2))
        self.assertTrue(model.syn1neg.shape == (len(model.vocab), 2))

        model.train(sentences)
        sims = model.most_similar('graph', topn=10)
        # self.assertTrue(sims[0][0] == 'trees', sims)  # most similar

        # test querying for "most similar" by vector
        graph_vector = model.syn0norm[model.vocab['graph'].index]
        sims2 = model.most_similar(positive=[graph_vector], topn=11)
        sims2 = [(w, sim) for w, sim in sims2 if w != 'graph']  # ignore 'graph' itself
        self.assertEqual(sims, sims2)

        # build vocab and train in one step; must be the same as above
        model2 = word2vec.Word2Vec(sentences, size=2, min_count=1, hs=0, negative=2)
        self.models_equal(model, model2)

    def testTrainingCbowNegative(self):
        """Test CBOW (negative sampling) word2vec training."""
        # to test training, make the corpus larger by repeating its sentences over and over
        # build vocabulary, don't train yet
        model = word2vec.Word2Vec(size=2, min_count=1, sg=0, hs=0, negative=2)
        model.build_vocab(sentences)
        self.assertTrue(model.syn0.shape == (len(model.vocab), 2))
        self.assertTrue(model.syn1neg.shape == (len(model.vocab), 2))

        model.train(sentences)
        sims = model.most_similar('graph', topn=10)
        # self.assertTrue(sims[0][0] == 'trees', sims)  # most similar

        # test querying for "most similar" by vector
        graph_vector = model.syn0norm[model.vocab['graph'].index]
        sims2 = model.most_similar(positive=[graph_vector], topn=11)
        sims2 = [(w, sim) for w, sim in sims2 if w != 'graph']  # ignore 'graph' itself
        self.assertEqual(sims, sims2)

        # build vocab and train in one step; must be the same as above
        model2 = word2vec.Word2Vec(sentences, size=2, min_count=1, sg=0, hs=0, negative=2)
        self.models_equal(model, model2)

    def testSimilarities(self):
        """Test similarity and n_similarity methods."""
        # The model is trained using CBOW
        model = word2vec.Word2Vec(size=2, min_count=1, sg=0, hs=0, negative=2)
        model.build_vocab(sentences)
        model.train(sentences)

        self.assertTrue(model.n_similarity(['graph', 'trees'], ['trees', 'graph']))
        self.assertTrue(model.n_similarity(['graph'], ['trees']) == model.similarity('graph', 'trees'))

    def testSimilarBy(self):
        """Test word2vec similar_by_word and similar_by_vector."""
        model = word2vec.Word2Vec(sentences, size=2, min_count=1, hs=1, negative=0)
        wordsims = model.similar_by_word('graph', topn=10)
        wordsims2 = model.most_similar(positive='graph', topn=10)
        vectorsims = model.similar_by_vector(model['graph'], topn=10)
        vectorsims2 = model.most_similar([model['graph']], topn=10)
        self.assertEqual(wordsims, wordsims2)
        self.assertEqual(vectorsims, vectorsims2)

    def testParallel(self):
        """Test word2vec parallel training."""
        if word2vec.FAST_VERSION < 0:  # don't test the plain NumPy version for parallelism (too slow)
            return

        corpus = utils.RepeatCorpus(LeeCorpus(), 10000)

        for workers in [2, 4]:
            model = word2vec.Word2Vec(corpus, workers=workers)
            sims = model.most_similar('israeli')
            # the exact vectors and therefore similarities may differ, due to different thread collisions/randomization
            # so let's test only for top3
            # TODO: commented out for now; find a more robust way to compare against "gold standard"
            # self.assertTrue('palestinian' in [sims[i][0] for i in range(3)])

    def testRNG(self):
        """Test word2vec results identical with identical RNG seed."""
        model = word2vec.Word2Vec(sentences, min_count=2, seed=42, workers=1)
        model2 = word2vec.Word2Vec(sentences, min_count=2, seed=42, workers=1)
        self.models_equal(model, model2)

    def models_equal(self, model, model2):
        self.assertEqual(len(model.vocab), len(model2.vocab))
        self.assertTrue(numpy.allclose(model.syn0, model2.syn0))
        if model.hs:
            self.assertTrue(numpy.allclose(model.syn1, model2.syn1))
        if model.negative:
            self.assertTrue(numpy.allclose(model.syn1neg, model2.syn1neg))
        most_common_word = max(model.vocab.items(), key=lambda item: item[1].count)[0]
        self.assertTrue(numpy.allclose(model[most_common_word], model2[most_common_word]))

    @log_capture()
    def testBuildVocabWarning(self, l):
        """Test if warning is raised on non-ideal input to a word2vec model"""
        sentences = ['human', 'machine']
        model = word2vec.Word2Vec()
        model.build_vocab(sentences)
        warning = "Each 'sentences' item should be a list of words (usually unicode strings)."
        self.assertTrue(warning in str(l))

    @log_capture()
    def testTrainWarning(self, l):
        """Test if warning is raised if alpha rises during subsequent calls to train()"""
        sentences = [['human'],
                     ['graph', 'trees']]
        model = word2vec.Word2Vec(min_count=1)
        model.build_vocab(sentences)
        for epoch in range(10):
            model.train(sentences)
            model.alpha -= 0.002
            model.min_alpha = model.alpha
            if epoch == 5:
                model.alpha += 0.05
        warning = "Effective 'alpha' higher than previous training cycles"
        self.assertTrue(warning in str(l))
#endclass TestWord2VecModel

    def test_sentences_should_not_be_a_generator(self):
        """
        Is sentences a generator object?
        """
        gen = (s for s in sentences)
        self.assertRaises(TypeError, word2vec.Word2Vec, (gen,))


class TestWMD(unittest.TestCase):
    def testNonzero(self):
        '''Test basic functionality with a test sentence.'''

        if not PYEMD_EXT:
            return

        model = word2vec.Word2Vec(sentences, min_count=2, seed=42, workers=1)
        sentence1 = ['human', 'interface', 'computer']
        sentence2 = ['survey', 'user', 'computer', 'system', 'response', 'time']
        distance = model.wmdistance(sentence1, sentence2)

        # Check that distance is non-zero.
        self.assertFalse(distance == 0.0)

    def testSymmetry(self):
        '''Check that distance is symmetric.'''

        if not PYEMD_EXT:
            return

        model = word2vec.Word2Vec(sentences, min_count=2, seed=42, workers=1)
        sentence1 = ['human', 'interface', 'computer']
        sentence2 = ['survey', 'user', 'computer', 'system', 'response', 'time']
        distance1 = model.wmdistance(sentence1, sentence2)
        distance2 = model.wmdistance(sentence2, sentence1)
        self.assertTrue(numpy.allclose(distance1, distance2))

    def testIdenticalSentences(self):
        '''Check that the distance from a sentence to itself is zero.'''

        if not PYEMD_EXT:
            return

        model = word2vec.Word2Vec(sentences, min_count=1)
        sentence = ['survey', 'user', 'computer', 'system', 'response', 'time']
        distance = model.wmdistance(sentence, sentence)
        self.assertEqual(0.0, distance)


class TestWord2VecSentenceIterators(unittest.TestCase):
    def testLineSentenceWorksWithFilename(self):
        """Does LineSentence work with a filename argument?"""
        with utils.smart_open(datapath('lee_background.cor')) as orig:
            sentences = word2vec.LineSentence(datapath('lee_background.cor'))
            for words in sentences:
                self.assertEqual(words, utils.to_unicode(orig.readline()).split())

    def testLineSentenceWorksWithCompressedFile(self):
        """Does LineSentence work with a compressed file object argument?"""
        with utils.smart_open(datapath('head500.noblanks.cor')) as orig:
            sentences = word2vec.LineSentence(bz2.BZ2File(datapath('head500.noblanks.cor.bz2')))
            for words in sentences:
                self.assertEqual(words, utils.to_unicode(orig.readline()).split())

    def testLineSentenceWorksWithNormalFile(self):
        """Does LineSentence work with a file object argument, rather than filename?"""
        with utils.smart_open(datapath('head500.noblanks.cor')) as orig:
            with utils.smart_open(datapath('head500.noblanks.cor')) as fin:
                sentences = word2vec.LineSentence(fin)
                for words in sentences:
                    self.assertEqual(words, utils.to_unicode(orig.readline()).split())
#endclass TestWord2VecSentenceIterators

# TODO: get correct path to Python binary
# class TestWord2VecScripts(unittest.TestCase):
#     def testWord2VecStandAloneScript(self):
#         """Does Word2Vec script launch standalone?"""
#         cmd = 'python -m gensim.scripts.word2vec_standalone -train ' + datapath('testcorpus.txt') + ' -output vec.txt -size 200 -sample 1e-4 -binary 0 -iter 3 -min_count 1'
#         output = check_output(cmd, stderr=PIPE)
#         self.assertEqual(output, '0')
# #endclass TestWord2VecScripts


if not hasattr(TestWord2VecModel, 'assertLess'):
    # workaround for python 2.6
    def assertLess(self, a, b, msg=None):
        self.assertTrue(a < b, msg="%s is not less than %s" % (a, b))

    setattr(TestWord2VecModel, 'assertLess', assertLess)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s : %(threadName)s : %(levelname)s : %(message)s',
        level=logging.DEBUG)
    logging.info("using optimization %s", word2vec.FAST_VERSION)
    unittest.main()
