from __future__ import division
from builtins import str
from builtins import range
from builtins import object
from past.utils import old_div
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


class TerrariumTile(mercator.MercatorTile):
    def __init__(self, parent, z, x, y):
        super(TerrariumTile, self).__init__(
            z, x, y, 256,
            parent.mercator.latlon_bbox(z, x, y),
            parent.mercator.mercator_bbox(z, x, y))
        self.output_dir = parent.output_dir

    def freeze_dry(self):
        return dict(type='terrarium', z=self.z, x=self.x, y=self.y)

    def render(self, tmp_dir):
        logger = logging.getLogger('terrarium')

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

            # we want the output to be 3-channels R, G, B with:
            #   uheight = height + 32768.0
            #   R = int(height) / 256
            #   G = int(height) % 256
            #   B = int(frac(height) * 256)
            # Looks like gdal doesn't handle "nodata" across multiple channels,
            # so we'll use R=0, which corresponds to height < 32,513 which is
            # lower than any depth on Earth, so we should be okay.
            mem_drv = gdal.GetDriverByName("MEM")
            mem_ds = mem_drv.Create('', dst_x_size, dst_y_size, 3, gdal.GDT_Byte)
            mem_ds.SetGeoTransform(dst_gt)
            mem_ds.SetProjection(dst_srs)
            mem_ds.GetRasterBand(1).SetNoDataValue(0)

            pixels = dst_ds.GetRasterBand(1).ReadAsArray(0, 0, dst_x_size, dst_y_size)
            # transform to uheight, clamping the range
            pixels += 32768.0
            numpy.clip(pixels, 0.0, 65535.0, out=pixels)

            r = (old_div(pixels, 256)).astype(numpy.uint8)
            res = mem_ds.GetRasterBand(1).WriteArray(r)
            assert res == gdal.CPLE_None

            g = (pixels % 256).astype(numpy.uint8)
            res = mem_ds.GetRasterBand(2).WriteArray(g)
            assert res == gdal.CPLE_None

            b = ((pixels * 256) % 256).astype(numpy.uint8)
            res = mem_ds.GetRasterBand(3).WriteArray(b)
            assert res == gdal.CPLE_None

            png_file = os.path.join(tmp_dir, self.output_dir,
                                    tile + ".png")
            png_drv = gdal.GetDriverByName("PNG")
            png_ds = png_drv.CreateCopy(png_file, mem_ds)

            # explicitly delete the datasources. the Python-GDAL docs suggest
            # that this is a good idea not only to dispose of memory buffers
            # but also to ensure that the backing file handles are closed.
            del mem_ds
            del png_ds

            assert os.path.isfile(png_file)

        source_names = [type(s).__name__ for s in self.sources]
        logger.info("Done generating tile %r from %s"
                    % (tile, ", ".join(source_names)))


class Terrarium(object):

    def __init__(self, regions, sources, options={}):
        self.regions = regions
        self.sources = sources
        self.output_dir = options.get('output_dir', 'terrarium_tiles')
        self.mercator = mercator.Mercator()

    def expand_tile(self, bbox, zoom_range):
        tiles = []

        for z in range(*zoom_range):
            lx, ly = self.mercator.lonlat_to_xy(z, bbox[0], bbox[1])
            ux, uy = self.mercator.lonlat_to_xy(z, bbox[2], bbox[3])
            ll = self.mercator.latlon_bbox(z, lx, ly).bounds
            ur = self.mercator.latlon_bbox(z, ux, uy).bounds
            res = max((ll[2] - ll[0]) / 256.0,
                      (ur[2] - ur[0]) / 256.0)
            tiles.append(RegionTile((ll[0], ll[1], ur[2], ur[3]), res))

        return tiles

    def generate_tiles(self):
        logger = logging.getLogger('terrarium')

        for r in self.regions:
            rbox = r.bbox.bounds
            for zoom in range(*r.zoom_range):
                lx, ly = self.mercator.lonlat_to_xy(zoom, rbox[0], rbox[3])
                ux, uy = self.mercator.lonlat_to_xy(zoom, rbox[2], rbox[1])

                logger.info("Generating %d tiles for region." % ((ux - lx + 1) * (uy - ly + 1),))
                for x in range(lx, ux + 1):
                    for y in range(ly, uy + 1):
                        yield TerrariumTile(self, zoom, x, y)

    def rehydrate(self, data):
        typ = data.get('type')
        assert typ == 'terrarium', "Unable to rehydrate tile of type %r in " \
            "terrarium output. Job was: %r" % (typ, data)

        z = data['z']
        x = data['x']
        y = data['y']
        return TerrariumTile(self, z, x, y)

def create(regions, sources, options):
    return Terrarium(regions, sources, options)
