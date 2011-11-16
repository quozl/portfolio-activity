# -*- coding: utf-8 -*-
#Copyright (c) 2011 Walter Bender

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software
# Foundation, 51 Franklin Street, Suite 500 Boston, MA 02110-1335 USA


import gtk
import gobject
import os

from math import sqrt, ceil

from sugar.activity import activity
from sugar import profile
try:
    from sugar.graphics.toolbarbox import ToolbarBox
    HAVE_TOOLBOX = True
except ImportError:
    HAVE_TOOLBOX = False

if HAVE_TOOLBOX:
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
    from sugar.graphics.toolbarbox import ToolbarButton

from sugar.datastore import datastore

from sprites import Sprites, Sprite
from exporthtml import save_html
from exportpdf import save_pdf
from utils import get_path, lighter_color, svg_str_to_pixbuf, \
    play_audio_from_file, get_pixbuf_from_journal, genblank, get_hardware
from toolbar_utils import radio_factory, \
    button_factory, separator_factory, combo_factory, label_factory
from grecord import Grecord

from gettext import gettext as _

import logging
_logger = logging.getLogger("portfolio-activity")

try:
    from sugar.graphics import style
    GRID_CELL_SIZE = style.GRID_CELL_SIZE
except ImportError:
    GRID_CELL_SIZE = 0

# Size and position of title, preview image, and description
PREVIEWW = 450
PREVIEWH = 338
PREVIEWY = 80
TITLEH = 60
DESCRIPTIONH = 350
DESCRIPTIONX = 50
DESCRIPTIONY = 450
# If the entry is an image, it is used instead of the preview
# and shown at a larger size...
FULLW = 800
FULLH = 600
# ...leaving less room for a description.
SHORTH = 100
SHORTX = 50
SHORTY = 700

TWO = 0
TEN = 1
THIRTY = 2
SIXTY = 3
UNITS = [_('2 seconds'), _('10 seconds'), _('30 seconds'), _('1 minute')]
UNIT_DICTIONARY = {TWO: (UNITS[TWO], 2),
                   TEN: (UNITS[TEN], 10),
                   THIRTY: (UNITS[THIRTY], 30),
                   SIXTY: (UNITS[SIXTY], 60)}
XO1 = 'xo1'
XO15 = 'xo1.5'
XO175 = 'xo1.75'
UNKNOWN = 'unknown'

# sprite layers
DRAG = 5
TOP = 4
UNDRAG = 3
MIDDLE = 2
BOTTOM = 1
HIDE = 0


class PortfolioActivity(activity.Activity):
    ''' Make a slideshow from starred Journal entries. '''

    def __init__(self, handle):
        ''' Initialize the toolbars and the work surface '''
        super(PortfolioActivity, self).__init__(handle)

        self.datapath = get_path(activity, 'instance')

        self._hw = get_hardware()

        self._setup_toolbars()
        self._setup_canvas()
        self._setup_workspace()

        self._thumbs = []
        self._thumbnail_mode = False

        self._recording = False
        self._grecord = None

    def _setup_canvas(self):
        ''' Create a canvas '''
        self._canvas = gtk.DrawingArea()
        self._canvas.set_size_request(gtk.gdk.screen_width(),
                                      gtk.gdk.screen_height())
        self.set_canvas(self._canvas)
        self._canvas.show()
        self.show_all()

        self._canvas.set_flags(gtk.CAN_FOCUS)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK)
        self._canvas.add_events(gtk.gdk.POINTER_MOTION_MASK)
        self._canvas.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
        self._canvas.add_events(gtk.gdk.KEY_PRESS_MASK)
        self._canvas.connect("expose-event", self._expose_cb)
        self._canvas.connect("button-press-event", self._button_press_cb)
        self._canvas.connect("button-release-event", self._button_release_cb)
        self._canvas.connect("motion-notify-event", self._mouse_move_cb)

    def _setup_workspace(self):
        ''' Prepare to render the datastore entries. '''
        self.colors = profile.get_color().to_string().split(',')

        # Use the lighter color for the text background
        if lighter_color(self.colors) == 0:
            tmp = self.colors[0]
            self.colors[0] = self.colors[1]
            self.colors[1] = tmp

        self._width = gtk.gdk.screen_width()
        self._height = gtk.gdk.screen_height()
        self._scale = gtk.gdk.screen_height() / 900.

        if self._hw[0:2] == 'xo':
            titlef = 18
            descriptionf = 12
        else:
            titlef = 36
            descriptionf = 24

        # Generate the sprites we'll need...
        self._sprites = Sprites(self._canvas)

        self._title = Sprite(self._sprites, 0, 0, svg_str_to_pixbuf(
                genblank(self._width, int(TITLEH * self._scale),
                          self.colors)))
        self._title.set_label_attributes(int(titlef * self._scale),
                                         rescale=False)
        self._preview = Sprite(self._sprites,
            int((self._width - int(PREVIEWW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(genblank(
                    int(PREVIEWW * self._scale), int(PREVIEWH * self._scale),
                    self.colors)))

        self._full_screen = Sprite(self._sprites,
            int((self._width - int(FULLW * self._scale)) / 2),
            int(PREVIEWY * self._scale), svg_str_to_pixbuf(
                genblank(int(FULLW * self._scale), int(FULLH * self._scale),
                          self.colors)))

        self._description = Sprite(self._sprites,
                                   int(DESCRIPTIONX * self._scale),
                                   int(DESCRIPTIONY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * DESCRIPTIONX * self._scale)),
                          int(DESCRIPTIONH * self._scale),
                          self.colors)))
        self._description.set_label_attributes(int(descriptionf * self._scale))

        self._description2 = Sprite(self._sprites,
                                   int(SHORTX * self._scale),
                                   int(SHORTY * self._scale),
                                   svg_str_to_pixbuf(
                genblank(int(self._width - (2 * SHORTX * self._scale)),
                          int(SHORTH * self._scale),
                          self.colors)))
        self._description2.set_label_attributes(
            int(descriptionf * self._scale))

        self._my_canvas = Sprite(
            self._sprites, 0, 0, svg_str_to_pixbuf(genblank(
                    self._width, self._height, (self.colors[0],
                                                self.colors[0]))))
        self._my_canvas.set_layer(BOTTOM)

        self._clear_screen()

        self._find_starred()
        self.i = 0
        self._show_slide()

        self._playing = False
        self._rate = 10

    def _setup_toolbars(self):
        ''' Setup the toolbars. '''

        self.max_participants = 1  # no sharing

        if HAVE_TOOLBOX:
            toolbox = ToolbarBox()

            # Activity toolbar
            activity_button_toolbar = ActivityToolbarButton(self)

            toolbox.toolbar.insert(activity_button_toolbar, 0)
            activity_button_toolbar.show()

            self.set_toolbar_box(toolbox)
            toolbox.show()
            self.toolbar = toolbox.toolbar

            adjust_toolbar = gtk.Toolbar()
            adjust_toolbar_button = ToolbarButton(
                label=_('Adjust'),
                page=adjust_toolbar,
                icon_name='preferences-system')
            adjust_toolbar.show_all()
            adjust_toolbar_button.show()

            record_toolbar = gtk.Toolbar()
            record_toolbar_button = ToolbarButton(
                label=_('Record a sound'),
                page=record_toolbar,
                icon_name='media-audio')
            record_toolbar.show_all()
            record_toolbar_button.show()
        else:
            # Use pre-0.86 toolbar design
            primary_toolbar = gtk.Toolbar()
            toolbox = activity.ActivityToolbox(self)
            self.set_toolbox(toolbox)
            toolbox.add_toolbar(_('Page'), primary_toolbar)
            adjust_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Adjust'), adjust_toolbar)
            record_toolbar = gtk.Toolbar()
            toolbox.add_toolbar(_('Record'), record_toolbar)
            toolbox.show()
            toolbox.set_current_toolbar(1)
            self.toolbar = primary_toolbar

        self._prev_button = button_factory(
            'go-previous-inactive', self.toolbar, self._prev_cb,
            tooltip=_('Prev slide'), accelerator='<Ctrl>P')

        self._next_button = button_factory(
            'go-next', self.toolbar, self._next_cb,
            tooltip=_('Next slide'), accelerator='<Ctrl>N')

        self._auto_button = button_factory(
            'media-playback-start', self.toolbar,
            self._autoplay_cb, tooltip=_('Autoplay'))

        if HAVE_TOOLBOX:
            toolbox.toolbar.insert(adjust_toolbar_button, -1)
            toolbox.toolbar.insert(record_toolbar_button, -1)

        label = label_factory(adjust_toolbar, _('Adjust playback speed'))
        label.show()

        separator_factory(adjust_toolbar, False, False)

        self._unit_combo = combo_factory(UNITS, adjust_toolbar,
                                         self._unit_combo_cb,
                                         default=UNITS[TEN],
                                         tooltip=_('Adjust playback speed'))
        self._unit_combo.show()

        separator_factory(adjust_toolbar)

        button_factory('system-restart', adjust_toolbar, self._rescan_cb,
                       tooltip=_('Refresh'))

        separator_factory(self.toolbar)

        slide_button = radio_factory('slide-view', self.toolbar,
                                     self._slides_cb, group=None,
                                     tooltip=_('Slide view'))

        radio_factory('thumbs-view', self.toolbar, self._thumbs_cb,
                      tooltip=_('Thumbnail view'),
                      group=slide_button)

        button_factory('view-fullscreen', self.toolbar,
                       self.do_fullscreen_cb, tooltip=_('Fullscreen'),
                       accelerator='<Alt>Return')

        label_factory(record_toolbar, _('Record a sound') + ':')
        self._record_button = button_factory(
            'media-record', record_toolbar,
            self._record_cb, tooltip=_('Start recording'))

        separator_factory(record_toolbar)

        self._playback_button = button_factory(
            'media-playback-start-insensitive',  record_toolbar,
            self._playback_recording_cb, tooltip=_('Nothing to play'))

        self._save_recording_button = button_factory(
            'sound-save-insensitive', record_toolbar,
            self._save_recording_cb, tooltip=_('Nothing to save'))

        if HAVE_TOOLBOX:
            separator_factory(activity_button_toolbar)

            self._save_html = button_factory(
                'save-as-html', activity_button_toolbar,
                self._save_as_html_cb, tooltip=_('Save as HTML'))
            self._save_pdf = button_factory(
                'save-as-pdf', activity_button_toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))
        else:
            separator_factory(self.toolbar)

            self._save_html = button_factory(
                'save-as-html', self.toolbar,
                self._save_as_html_cb, tooltip=_('Save as HTML'))
            self._save_pdf = button_factory(
                'save-as-pdf', self.toolbar,
                self._save_as_pdf_cb, tooltip=_('Save as PDF'))

        if HAVE_TOOLBOX:
            separator_factory(toolbox.toolbar, True, False)

            stop_button = StopButton(self)
            stop_button.props.accelerator = '<Ctrl>q'
            toolbox.toolbar.insert(stop_button, -1)
            stop_button.show()

    def _destroy_cb(self, win, event):
        ''' Clean up on the way out. '''
        gtk.main_quit()

    def _find_starred(self):
        ''' Find all the favorites in the Journal. '''
        self.dsobjects, self._nobjects = datastore.find({'keep': '1'})
        _logger.debug('found %d starred items', self._nobjects)
        return

    def _prev_cb(self, button=None):
        ''' The previous button has been clicked; goto previous slide. '''
        if self.i > 0:
            self.i -= 1
            self._show_slide()

    def _next_cb(self, button=None):
        ''' The next button has been clicked; goto next slide. '''
        if self.i < self._nobjects - 1:
            self.i += 1
            self._show_slide()

    def _rescan_cb(self, button=None):
        ''' Rescan the Journal for changes in starred items. '''
        self._find_starred()
        self.i = 0
        # Reset thumbnails
        self._thumbs = []
        if self._thumbnail_mode:
            self._thumbnail_mode = False
            self._thumbs_cb()
        else:
            self._show_slide()

    def _autoplay_cb(self, button=None):
        ''' The autoplay button has been clicked; step through slides. '''
        if self._playing:
            self._stop_autoplay()
        else:
            if self._thumbnail_mode:
                self._thumbnail_mode = False
                self.i = self._current_slide
            self._playing = True
            self._auto_button.set_icon('media-playback-pause')
            self._loop()

    def _stop_autoplay(self):
        ''' Stop autoplaying. '''
        self._playing = False
        self._auto_button.set_icon('media-playback-start')
        if hasattr(self, '_timeout_id') and self._timeout_id is not None:
            gobject.source_remove(self._timeout_id)

    def _loop(self):
        ''' Show a slide and then call oneself with a timeout. '''
        self.i += 1
        if self.i == self._nobjects:
            self.i = 0
        self._show_slide()
        self._timeout_id = gobject.timeout_add(int(self._rate * 1000),
                                               self._loop)

    def _bump_test(self):
        ''' Test for accelerometer event (XO 1.75 only). '''
        if self._thumbnail_mode:
            return

        self._bump_id = None

        fh = open('/sys/devices/platform/lis3lv02d/position')
        string = fh.read()
        fh.close()
        xyz = string[1:-2].split(',')
        dx = int(xyz[0])

        if dx > 250:
            if self.i < self._nobjects - 2:
                self.i += 1
                self._show_slide()
        elif dx < -250:
            if self.i > 0:
                self.i -= 1
                self._show_slide()
        else:
            self._bump_id = gobject.timeout_add(int(100), self._bump_test)

    def _save_as_html_cb(self, button=None):
        ''' Export an HTML version of the slideshow to the Journal. '''
        results = save_html(self, profile.get_nick_name())
        html_file = os.path.join(self.datapath, 'tmp.html')
        tmp_file = open(html_file, 'w')
        tmp_file.write(results)
        tmp_file.close()

        dsobject = datastore.create()
        dsobject.metadata['title'] = profile.get_nick_name() + ' ' + \
                                     _('Portfolio')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'text/html'
        dsobject.set_file_path(html_file)
        dsobject.metadata['activity'] = 'org.laptop.WebActivity'
        datastore.write(dsobject)
        dsobject.destroy()
        return

    def _save_as_pdf_cb(self, button=None):
        ''' Export an PDF version of the slideshow to the Journal. '''
        tmp_file = save_pdf(self, profile.get_nick_name())

        dsobject = datastore.create()
        dsobject.metadata['title'] = profile.get_nick_name() + ' ' + \
                                     _('Portfolio')
        dsobject.metadata['icon-color'] = profile.get_color().to_string()
        dsobject.metadata['mime_type'] = 'application/pdf'
        dsobject.set_file_path(tmp_file)
        dsobject.metadata['activity'] = 'org.laptop.sugar.ReadActivity'
        datastore.write(dsobject)
        dsobject.destroy()
        return

    def _clear_screen(self):
        ''' Clear the screen to the darker of the two XO colors. '''
        self._title.hide()
        self._full_screen.hide()
        self._preview.hide()
        self._description.hide()
        if hasattr(self, '_thumbs'):
            for thumbnail in self._thumbs:
                thumbnail[0].hide()
        self.invalt(0, 0, self._width, self._height)

        # Reset drag settings
        self._press = None
        self._release = None
        self._dragpos = [0, 0]
        self._total_drag = [0, 0]
        self.last_spr_moved = None

    def _show_slide(self):
        ''' Display a title, preview image, and decription for slide
        i. Play an audio note if there is one recorded for this
        object. '''
        self._clear_screen()

        if self._nobjects == 0:
            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')
            self._description.set_label(
                _('Do you have any items in your Journal starred?'))
            self._description.set_layer(MIDDLE)
            return

        if self.i == 0:
            self._prev_button.set_icon('go-previous-inactive')
        else:
            self._prev_button.set_icon('go-previous')
        if self.i == self._nobjects - 1:
            self._next_button.set_icon('go-next-inactive')
        else:
            self._next_button.set_icon('go-next')

        pixbuf = None
        media_object = False
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                self.dsobjects[self.i].file_path, int(PREVIEWW * self._scale),
                int(PREVIEWH * self._scale))
            media_object = True
        except:
            pixbuf = get_pixbuf_from_journal(self.dsobjects[self.i], 300, 225)

        if pixbuf is not None:
            if not media_object:
                self._preview.set_shape(pixbuf.scale_simple(
                    int(PREVIEWW * self._scale),
                    int(PREVIEWH * self._scale),
                    gtk.gdk.INTERP_TILES))
                self._full_screen.hide()
                self._preview.set_layer(MIDDLE)
            else:
                self._full_screen.set_shape(pixbuf.scale_simple(
                    int(FULLW * self._scale),
                    int(FULLH * self._scale),
                    gtk.gdk.INTERP_TILES))
                self._full_screen.set_layer(MIDDLE)
                self._preview.hide()
        else:
            if self._preview is not None:
                self._preview.hide()
                self._full_screen.hide()

        self._title.set_label(self.dsobjects[self.i].metadata['title'])
        self._title.set_layer(MIDDLE)

        if 'description' in self.dsobjects[self.i].metadata:
            if media_object:
                self._description2.set_label(
                    self.dsobjects[self.i].metadata['description'])
                self._description2.set_layer(MIDDLE)
                self._description.set_label('')
                self._description.hide()
            else:
                self._description.set_label(
                    self.dsobjects[self.i].metadata['description'])
                self._description.set_layer(MIDDLE)
                self._description2.set_label('')
                self._description2.hide()
        else:
            self._description.set_label('')
            self._description.hide()
            self._description2.set_label('')
            self._description2.hide()

        audio_obj = self._search_for_audio_note(
            self.dsobjects[self.i].object_id)
        if audio_obj is not None:
            gobject.idle_add(play_audio_from_file, audio_obj.file_path)
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
        else:
            self._playback_button.set_icon('media-playback-start-insensitive')
            self._playback_button.set_tooltip(_('Nothing to play'))

        if self._hw == XO175:
            if hasattr(self, '_bump_id') and self._bump_id is not None:
                gobject.source_remove(self._bump_id)
            self._bump_id = gobject.timeout_add(1000, self._bump_test)

    def _slides_cb(self, button=None):
        if self._thumbnail_mode:
            self._thumbnail_mode = False
            self.i = self._current_slide
            self._show_slide()

    def _thumbs_cb(self, button=None):
        ''' Toggle between thumbnail view and slideshow view. '''
        if not self._thumbnail_mode:
            self._stop_autoplay()
            self._current_slide = self.i
            self._thumbnail_mode = True
            self._clear_screen()

            self._prev_button.set_icon('go-previous-inactive')
            self._next_button.set_icon('go-next-inactive')

            n = int(ceil(sqrt(self._nobjects)))
            if n > 0:
                w = int(self._width / n)
            else:
                w = self._width
            h = int(w * 0.75)  # maintain 4:3 aspect ratio
            x_off = int((self._width - n * w) / 2)
            x = x_off
            y = 0
            for i in range(self._nobjects):
                self.i = i
                self._show_thumb(x, y, w, h)
                x += w
                if x + w > self._width:
                    x = x_off
                    y += h
            self.i = 0  # Reset position in slideshow to the beginning
        return False

    def _show_thumb(self, x, y, w, h):
        ''' Display a preview image and title as a thumbnail. '''

        if len(self._thumbs) < self.i + 1:
            # Create a Sprite for this thumbnail
            pixbuf = None
            try:
                pixbuf = gtk.gdk.pixbuf_new_from_file_at_size(
                    self.dsobjects[self.i].file_path, int(w), int(h))
            except:
                pixbuf = get_pixbuf_from_journal(self.dsobjects[self.i],
                                                 int(w), int(h))

            if pixbuf is not None:
                pixbuf_thumb = pixbuf.scale_simple(int(w), int(h),
                                                   gtk.gdk.INTERP_TILES)
            else:
                pixbuf_thumb = svg_str_to_pixbuf(genblank(int(w), int(h),
                                                          self.colors))
            self._thumbs.append([Sprite(self._sprites, x, y, pixbuf_thumb),
                                     x, y, self.i])
            self._thumbs[-1][0].set_label(str(self.i + 1))
        self._thumbs[self.i][0].set_layer(TOP)

    def _expose_cb(self, win, event):
        ''' Callback to handle window expose events '''
        self.do_expose_event(event)
        return True

    # Handle the expose-event by drawing
    def do_expose_event(self, event):

        # Create the cairo context
        cr = self.canvas.window.cairo_create()

        # Restrict Cairo to the exposed area; avoid extra work
        cr.rectangle(event.area.x, event.area.y,
                event.area.width, event.area.height)
        cr.clip()

        # Refresh sprite list
        self._sprites.redraw_sprites(cr=cr)

    def do_fullscreen_cb(self, button):
        ''' Hide the Sugar toolbars. '''
        self.fullscreen()

    def invalt(self, x, y, w, h):
        ''' Mark a region for refresh '''
        self._canvas.window.invalidate_rect(
            gtk.gdk.Rectangle(int(x), int(y), int(w), int(h)), False)

    def _spr_to_thumb(self, spr):
        ''' Find which entry in the thumbnails table matches spr. '''
        for i, thumb in enumerate(self._thumbs):
            if spr == thumb[0]:
                return i
        return -1

    def _spr_is_thumbnail(self, spr):
        ''' Does spr match an entry in the thumbnails table? '''
        if self._spr_to_thumb(spr) == -1:
            return False
        else:
            return True

    def _button_press_cb(self, win, event):
        ''' The mouse button was pressed. Is it on a thumbnail sprite? '''
        win.grab_focus()
        x, y = map(int, event.get_coords())

        self._dragpos = [x, y]
        self._total_drag = [0, 0]

        spr = self._sprites.find_sprite((x, y))
        self._press = None
        self._release = None

        # Are we clicking on a thumbnail?
        if not self._spr_is_thumbnail(spr):
            return False

        self.last_spr_moved = spr
        self._press = spr
        self._press.set_layer(DRAG)
        return False

    def _mouse_move_cb(self, win, event):
        """ Drag a thumbnail with the mouse. """
        spr = self._press
        if spr is None:
            self._dragpos = [0, 0]
            return False
        win.grab_focus()
        x, y = map(int, event.get_coords())
        dx = x - self._dragpos[0]
        dy = y - self._dragpos[1]
        spr.move_relative([dx, dy])
        self._dragpos = [x, y]
        self._total_drag[0] += dx
        self._total_drag[1] += dy
        return False

    def _button_release_cb(self, win, event):
        ''' Button event is used to swap slides or goto next slide. '''
        win.grab_focus()
        self._dragpos = [0, 0]
        x, y = map(int, event.get_coords())

        if self._thumbnail_mode:
            # Drop the dragged thumbnail below the other thumbnails so
            # that you can find the thumbnail beneath it.
            self._press.set_layer(UNDRAG)
            i = self._spr_to_thumb(self._press)
            spr = self._sprites.find_sprite((x, y))
            if self._spr_is_thumbnail(spr):
                self._release = spr
                # If we found a thumbnail and it is not the one we
                # dragged, swap their positions.
                if not self._press == self._release:
                    j = self._spr_to_thumb(self._release)
                    self._thumbs[i][0] = self._release
                    self._thumbs[j][0] = self._press
                    tmp = self.dsobjects[i]
                    self.dsobjects[i] = self.dsobjects[j]
                    self.dsobjects[j] = tmp
                    self._thumbs[j][0].move((self._thumbs[j][1],
                                             self._thumbs[j][2]))
            self._thumbs[i][0].move((self._thumbs[i][1], self._thumbs[i][2]))
            self._press.set_layer(TOP)
            self._press = None
            self._release = None
        else:
            self._next_cb()
        return False

    def _unit_combo_cb(self, arg=None):
        ''' Read value of predefined conversion factors from combo box '''
        if hasattr(self, '_unit_combo'):
            active = self._unit_combo.get_active()
            if active in UNIT_DICTIONARY:
                self._rate = UNIT_DICTIONARY[active][1]

    def _record_cb(self, button=None):
        if self._grecord is None:
            self._grecord = Grecord(self)
        if self._recording:
            self._grecord.stop_recording_audio()
            self._recording = False
            self._record_button.set_icon('media-record')
            self._record_button.set_tooltip(_('Start recording'))
            self._playback_button.set_icon('media-playback-start')
            self._playback_button.set_tooltip(_('Play recording'))
            self._save_recording_button.set_icon('sound-save')
            self._save_recording_button.set_tooltip(_('Save recording'))
        else:
            self._grecord.record_audio()
            self._recording = True
            self._record_button.set_icon('media-recording')
            self._record_button.set_tooltip(_('Stop recording'))
            # Autosave if there was not already a recording
            if self._search_for_audio_note(
                self.dsobjects[self.i].object_id) is None:
                self._save_recording_cb()

    def _playback_recording_cb(self, button=None):
        ''' Play back current recording '''
        play_audio_from_file(os.path.join(self.datapath,
                                          'output.ogg'))
        return

    def _save_recording_cb(self, button=None):
        if os.path.exists(os.path.join(self.datapath, 'output.ogg')):
            obj_id = self.dsobjects[self.i].object_id
            os.rename(os.path.join(self.datapath, 'output.ogg'),
                      os.path.join(self.datapath, obj_id + '.ogg'))
            dsobject = self._search_for_audio_note(obj_id)
            if dsobject is None:
                dsobject = datastore.create()

            if dsobject is not None:
                dsobject.metadata['title'] = _('audio note for %s') % \
                    self.dsobjects[self.i].metadata['title']
                dsobject.metadata['icon-color'] = \
                    profile.get_color().to_string()
                dsobject.metadata['tags'] = obj_id
                dsobject.metadata['mime_type'] = 'audio/ogg'
                dsobject.set_file_path(os.path.join(self.datapath,
                                                    obj_id + '.ogg'))
                datastore.write(dsobject)
                dsobject.destroy()
        return

    def _search_for_audio_note(self, obj_id):
        ''' Look to see if there is already a sound recorded for this
        dsobject '''
        dsobjects, nobjects = datastore.find({'mime_type': ['audio/ogg']})
        # Look for tag that matches the target object id
        for dsobject in dsobjects:
            if 'tags' in dsobject.metadata and \
                    obj_id in dsobject.metadata['tags']:
                return dsobject
        return None
