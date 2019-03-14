#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2019 David Lilien <dlilien90@gmail.com>
#
# Distributed under terms of the GNU GPL3.0 license.

"""

"""

import os
import unittest
import numpy as np
from impdar.lib.RadarData import RadarData
from impdar.lib.RadarFlags import RadarFlags
from impdar.lib import horizontal_filters

THIS_DIR = os.path.dirname(os.path.abspath(__file__))

data_dummy = np.ones((500, 400))


class NoInitRadarData(RadarData):
    # This only exists so we can do tests on writing without reading

    def __init__(self):
        self.data = data_dummy
        self.dt = 0.1
        self.tnum = self.data.shape[1]
        self.snum = self.data.shape[0]
        self.travel_time = 0.001 * np.arange(self.data.shape[0]) + 0.001
        self.dt = 1
        self.flags = RadarFlags()
        self.hfilt_target_output = data_dummy * np.atleast_2d(1. - np.exp(-self.travel_time.flatten() * 0.05) / np.exp(-self.travel_time[0] * 0.05)).transpose()
        pexp = np.exp(-self.travel_time.flatten() * 0.05) / np.exp(-self.travel_time[0] * 0.05)
        pexp = pexp - pexp[-1]
        pexp = pexp / np.max(pexp)
        self.pexp_target_output = data_dummy * np.atleast_2d(1. - pexp).transpose()
        self.ahfilt_target_output = np.zeros_like(data_dummy)


class TestAdaptive(unittest.TestCase):

    def test_AdaptiveRun(self):
        radardata = NoInitRadarData()
        horizontal_filters.adaptivehfilt(radardata)
        # since we subtract average trace and all traces are identical, we should get zeros out
        self.assertTrue(np.all(radardata.data == radardata.ahfilt_target_output))


class TestHfilt(unittest.TestCase):

    def test_HfiltRun(self):
        radardata = NoInitRadarData()
        horizontal_filters.hfilt(radardata, 0, 100)
        # We taper in the hfilt, so this is not just zeros
        self.assertTrue(np.all(radardata.data == radardata.hfilt_target_output))


class TestHighPass(unittest.TestCase):

    def test_HighPass(self):
        radardata = NoInitRadarData()
        horizontal_filters.highpass(radardata, 10., 1)
        # There is no high-frequency variability, so this result should be small
        # We only have residual variability from the quality of the filter
        self.assertTrue(np.allclose(radardata.data, np.zeros_like(data_dummy)))

    def test_HighPassBadcutoff(self):
        radardata = NoInitRadarData()
        with self.assertRaises(ValueError):
            # We have a screwed up filter here because of sampling vs. frequency used
            horizontal_filters.highpass(radardata, 10., 100)


class TestWinAvgHfilt(unittest.TestCase):

    def test_WinAvgExp(self):
        radardata = NoInitRadarData()
        horizontal_filters.winavg_hfilt(radardata, 11, taper='full')
        self.assertTrue(np.all(radardata.data == radardata.hfilt_target_output))

    def test_WinAvgExpBadwinavg(self):
        # Tests the check on whether win_avg < tnum
        radardata = NoInitRadarData()
        horizontal_filters.winavg_hfilt(radardata, data_dummy.shape[1] + 10, taper='full')
        self.assertTrue(np.all(radardata.data == radardata.hfilt_target_output))

    def test_WinAvgPexp(self):
        radardata = NoInitRadarData()
        horizontal_filters.winavg_hfilt(radardata, 11, taper='pexp', filtdepth=-1)
        self.assertTrue(np.all(radardata.data == radardata.pexp_target_output))

    def test_WinAvgbadtaper(self):
        radardata = NoInitRadarData()
        with self.assertRaises(ValueError):
            horizontal_filters.winavg_hfilt(radardata, 11, taper='not_a_taper', filtdepth=-1)


class TestRadarDataHfiltWrapper(unittest.TestCase):

    def test_AdaptiveRun(self):
        radardata = NoInitRadarData()
        radardata.hfilt('adaptive')
        # since we subtract average trace and all traces are identical, we should get zeros out
        self.assertTrue(np.all(radardata.data == radardata.ahfilt_target_output))

    def test_HfiltRun(self):
        radardata = NoInitRadarData()
        radardata.hfilt('hfilt', (0, 100))
        # We taper in the hfilt, so this is not just zeros
        self.assertTrue(np.all(radardata.data == radardata.hfilt_target_output))


if __name__ == '__main__':
    unittest.main()