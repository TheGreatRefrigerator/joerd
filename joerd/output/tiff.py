from builtins import str
from builtins import range
from builtins import object
from joerd.util import BoundingBox
from joerd.region import RegionTile
from joerd.mkdir_p import mkdir_p
from tempfile import NamedTemporaryFile as Tmp
from osgeo import osr, gdal
import re
import logging
import os
import os.path
import tempfile
import subprocess
import shutil
import errno
import sys
import joerd.composite as composite
import joerd.mercator as mercator
import numpy


class TiffTile(mercator.MercatorTile):
    def __init__(self, parent, z, x, y):
        super(TiffTile, self).__init__(
            z, x, y, 512,
            parent.mercator.latlon_bbox(z, x, y),
            parent.mercator.mercator_bbox(z, x, y))
        self.output_dir = parent.output_dir

    def freeze_dry(self):
        return dict(type='tiff', z=self.z, x=self.x, y=self.y)

    def render(self, tmp_dir):
        logger = logging.getLogger('tiff')

        bbox = self._mercator_bbox

        mid_dir = os.path.join(tmp_dir, self.output_dir,
                               str(self.z), str(self.x))
        mkdir_p(mid_dir)

        tile = self.tile_name()
        logger.debug("Generating tile %r..." % tile)

        with self.get_datasource(logger) as dst_ds:
            dst_srs = dst_ds.GetProjection()
            dst_gt = dst_ds.GetGeoTransform()
            dst_x_size = dst_ds.RasterXSize
            dst_y_size = dst_ds.RasterYSize

            # TIFF compresses best if we stick to integer pixels, using LZW
            # and the "2" type predictor. we might be able to keep some bits
            # of precision with float32 and DISCARD_LSB, but that's only
            # available in GDAL >= 2.0
            tile_file = os.path.join(tmp_dir, self.output_dir,
                                     tile + ".tif")
            outfile = tile_file
            tif_drv = gdal.GetDriverByName("GTiff")
            tif_ds = tif_drv.Create(outfile, dst_x_size, dst_y_size, 1,
                                    gdal.GDT_Int16, options = [
                                        'TILED=YES',
                                        'BLOCKXSIZE=256',
                                        'BLOCKYSIZE=256',
                                        'COMPRESS=LZW',
                                        'PREDICTOR=2'
                                    ])
            tif_ds.SetGeoTransform(dst_gt)
            tif_ds.SetProjection(dst_srs)
            tif_ds.GetRasterBand(1).SetNoDataValue(-32768)

            pixels = dst_ds.GetRasterBand(1).ReadAsArray(0, 0, dst_x_size, dst_y_size)
            # transform to integer height, clamping the range
            numpy.clip(pixels, -32768, 32767, out=pixels)
            tif_ds.GetRasterBand(1).WriteArray(pixels.astype(numpy.int16))

            # explicitly delete the datasources. the Python-GDAL docs suggest that
            # this is a good idea not only to dispose of memory buffers but also
            # to ensure that the backing file handles are closed.
            del tif_ds

            assert os.path.isfile(tile_file)

        source_names = [type(s).__name__ for s in self.sources]
        logger.info("Done generating tile %r from %s"
                    % (tile, ", ".join(source_names)))


class Tiff(object):

    def __init__(self, regions, sources, options={}):
        self.regions = regions
        self.sources = sources
        self.output_dir = options.get('output_dir', 'tiff_tiles')
        self.mercator = mercator.Mercator()

    def expand_tile(self, bbox, zoom_range):
        tiles = []

        for z in range(*zoom_range):
            lx, ly = self.mercator.lonlat_to_xy(z, bbox[0], bbox[1])
            ux, uy = self.mercator.lonlat_to_xy(z, bbox[2], bbox[3])
            ll = self.mercator.latlon_bbox(z, lx, ly).bounds
            ur = self.mercator.latlon_bbox(z, ux, uy).bounds
            res = max((ll[2] - ll[0]) / 512.0,
                      (ur[2] - ur[0]) / 512.0)
            tiles.append(RegionTile((ll[0], ll[1], ur[2], ur[3]), res))

        return tiles

    def generate_tiles(self):
        logger = logging.getLogger('tiff')

        # so here's where this whole thing with zooms breaks down: the tiles
        # from this provider are 512x512 (i.e: "retina") and a tile at zoom
        # z is equivalent in resolution to a normal tile at z+1. the "zooms"
        # in the config are easier-to-understand proxies for resolutions, so
        # this code should shift them by -1, clipping at zero, to maintain
        # the same resolution basis.
        for r in self.regions:
            rbox = r.bbox.bounds
            for zoom in range(max(0, r.zoom_range[0] - 1),
                              max(0, r.zoom_range[1] - 1)):
                lx, ly = self.mercator.lonlat_to_xy(zoom, rbox[0], rbox[3])
                ux, uy = self.mercator.lonlat_to_xy(zoom, rbox[2], rbox[1])

                logger.info("Generating %d tiles for region." % ((ux - lx + 1) * (uy - ly + 1),))
                for x in range(lx, ux + 1):
                    for y in range(ly, uy + 1):
                        yield TiffTile(self, zoom, x, y)

    def rehydrate(self, data):
        typ = data.get('type')
        assert typ == 'tiff', "Unable to rehydrate tile of type %r in " \
            "tiff output. Job was: %r" % (typ, data)

        z = data['z']
        x = data['x']
        y = data['y']
        return TiffTile(self, z, x, y)

def create(regions, sources, options):
    return Tiff(regions, sources, options)
