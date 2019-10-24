from __future__ import absolute_import
from builtins import object
from .ned_base import NEDBase
import re
import os.path


NORMAL_PATTERN = re.compile('^ned19_' \
                            '([ns])([0-9]{2})x([0257][05])_' \
                            '([ew])([0-9]{3})x([0257][05])_' \
                            '[a-z]{2}(_(?!topobathy)[a-z0-9]+)+' \
                            '_20[0-9]{2}.(zip|img)$')


class NED(object):
    def __init__(self, options={}):
        options = options.copy()
        options['pattern'] = NORMAL_PATTERN
        options['base_dir'] = options.get('base_dir', 'ned')
        self.base = NEDBase(False, options)

    def get_index(self):
        return self.base.get_index()

    def existing_files(self):
        return self.base.existing_files()

    def downloads_for(self, tile):
        return self.base.downloads_for(tile)

    def vrts_for(self, tile):
        return self.base.vrts_for(tile)

    def filter_type(self, src_res, dst_res):
        return self.base.filter_type(src_res, dst_res)

    def srs(self):
        return self.base.srs()

    def rehydrate(self, tile):
        return self.base.rehydrate(tile)


def create(options):
    return NED(options)
