
""" support for all XmEye cameras (chinease based DVRs and cameras) """
from socket import AF_INET, AF_UNIX, SOCK_STREAM, socket as Socket
from typing import List, NoReturn
import os, signal
from stat import S_IRUSR, S_IWUSR
from shutil import copyfileobj
import asyncio

from homeassistant.components.camera import Camera

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD,
    CONF_NAME)

from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
import logging
_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }),
}, extra=vol.PREVENT_EXTRA)

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    
    host = str(config.get(CONF_HOST))
    port = int(config.get(CONF_PORT))
    username = str(config.get(CONF_USERNAME))
    password = str(config.get(CONF_PASSWORD))
    if(password is None):
        password = ''
    _LOGGER.info("Connecting to %s:%i using %s:%s" % 
                (host, port, username, password))
    
    from dvrip.io import DVRIPClient
    
    client = DVRIPClient(Socket(AF_INET, SOCK_STREAM))
    client.connect((host, port), username, password)
    info = client.systeminfo()
    _LOGGER.info("Connected to %s. It has %i video-in. Will add %i cameras" % 
                (info.board, info.videoin, info.videoin))
    cameras = []
    for camera in range(int(info.videoin)):
        _LOGGER.info("Detected video-in nr %i" % (camera))
        cameras.append(XMEye_Camera(hass, client, camera, (host, port) ) )
    
    async_add_entities(cameras)

class XMEye_Camera(Camera):
    
    def __init__(self, hass, client, channel, remote):
        super().__init__()
        
        self._hass = hass
        self._client = client
        self._ffmpeg_manager = hass.data['ffmpeg']
        self._remote = remote
        self._info = self._client.systeminfo()
        self._channel = channel
        self._name = "%s_%i" % (self._info.board, channel)
        self._sock = Socket(AF_INET, SOCK_STREAM) # for streaming video
        self._sock.connect(self._remote)
        from dvrip.monitor import Stream
        self._reader = lambda: self._client.monitor(self._sock, self._channel, Stream["HD"])
        self._named_pipe = "/tmp/" + self._name
        if os.path.exists(self._named_pipe):
            os.unlink(self._named_pipe)
        os.mkfifo(self._named_pipe, S_IRUSR|S_IWUSR)

    @property
    def model(self):
        return self._info.board

    @property
    def name(self):
        return self._name

    async def async_camera_image(self):
        """Return a still image response from the camera."""

        #self._hass.async_create_task(async_reader_job(self._named_pipe, self._reader))

        from haffmpeg.tools import ImageFrame, IMAGE_JPEG
        ffmpeg = ImageFrame(self._ffmpeg_manager.binary, loop=self.hass.loop)

        image = await asyncio.shield(ffmpeg.get_image(
            self._named_pipe, output_format=IMAGE_JPEG))
        return image

        
async def async_reader_job(named_pipe, reader):

    with open(named_pipe, 'wb') as out:
        while True:
            try:
                chunk = reader.read(16)
                if not chunk:
                    break
                out.write(chunk)
                out.flush()
            finally:
                pass
                

