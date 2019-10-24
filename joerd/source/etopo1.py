from builtins import object
from joerd.util import BoundingBox
import joerd.download as download
import joerd.check as check
import joerd.srs as srs
from joerd.mkdir_p import mkdir_p
from shutil import copyfile
import os.path
import os
import requests
import logging
import re
import tempfile
import sys
import zipfile
import traceback
import subprocess
import glob
from osgeo import gdal


class ETOPO1(object):

    def __init__(self, options={}):
        self.base_dir = options.get('base_dir', 'etopo1')
        self.etopo1_url = options['url']
        self.download_options = options
        self.target_name = 'ETOPO1_Bed_g_geotiff.tif'

    def get_index(self):
        # ETOPO1 needs no index - it's a single file, for which we'll need
        # a directory to call home.
        if not os.path.isdir(self.base_dir):
            os.makedirs(self.base_dir)

    def existing_files(self):
        if os.path.exists(self.output_file()):
            yield self.output_file()

    def freeze_dry(self):
        # there's only one ETOPO1 tile
        return dict(type='etopo1')

    def rehydrate(self, data):
        assert data.get('type') == 'etopo1', \
            "Unable to rehydrate %r from ETOPO1." % data
        return self

    def downloads_for(self, tile):
        # There's just one thing to download, and it's this single world
        # tile.
        return set([self])

    def vrts_for(self, tile):
        """
        Returns a list of sets of tiles, with each list element intended as a
        separate VRT for use in GDAL.

        The reason for this is that GDAL doesn't do any compositing _within_
        a single VRT, so if there are multiple overlapping source rasters in
        the VRT, only one will be chosen. This isn't often the case - most
        raster datasets are non-overlapping apart from deliberately duplicated
        margins.
        """
        return [self.downloads_for(tile)]

    def output_file(self):
        return os.path.join(self.base_dir, self.target_name)

    def urls(self):
        return [self.etopo1_url]

    def options(self):
        return self.download_options

    def verifier(self):
        return check.is_zip

    def unpack(self, store, tmp):
        with store.upload_dir() as target:
            target_dir = os.path.join(target, self.base_dir)
            mkdir_p(target_dir)

            with zipfile.ZipFile(tmp.name, 'r') as zfile:
                zfile.extract(self.target_name, target_dir)

    def srs(self):
        return srs.wgs84()

    def filter_type(self, src_res, dst_res):
        return gdal.GRA_Lanczos


def create(options):
    return ETOPO1(options)
