# -*- coding: utf-8 -*-
# vim:et sts=4 sw=4
#
# ibus-typing-booster - A completion input method for IBus
#
# Copyright (c) 2017 Mike FABIAN <mfabian@redhat.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

'''
An emoji picker for ibus typing booster.
'''

import sys
import os
import re
import signal
import argparse
import locale
import time
import gettext
import unicodedata
import html
import itb_util
import itb_pango

from gi import require_version
require_version('GLib', '2.0')
from gi.repository import GLib

# set_prgname before importing other modules to show the name in warning
# messages when import modules are failed. E.g. Gtk.
GLib.set_application_name('Emoji Picker')
# This makes gnome-shell load the .desktop file when running under Wayland:
GLib.set_prgname('emoji-picker')

require_version('Gdk', '3.0')
from gi.repository import Gdk
require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import GObject
import itb_emoji
import version

GTK_VERSION = (Gtk.get_major_version(),
               Gtk.get_minor_version(),
               Gtk.get_micro_version())

DOMAINNAME = 'ibus-typing-booster'
_ = lambda a: gettext.dgettext(DOMAINNAME, a)
N_ = lambda a: a

def parse_args():
    '''
    Parse the command line arguments.
    '''
    parser = argparse.ArgumentParser(
        description='An emoji picker for ibus-typing-booster')
    parser.add_argument(
        '-l', '--languages',
        nargs='?',
        type=str,
        action='store',
        default='',
        help=('Set a list of languages to be used when browsing '
              + 'or searching for emoji. For example: '
              + '"emoji-picker -l de:fr:ja" '
              + 'would use German, French, and Japanese. '
              + 'If empty, the locale settings are used to '
              + 'determine the languages.'))
    parser.add_argument(
        '-f', '--font',
        nargs='?',
        type=str,
        action='store',
        default=None,
        help=('Set a font to display emoji. '
              + 'If not specified, the font is read from the config file. '
              + 'To use the system default font specify "emoji". '
              + 'default: "%(default)s"'))
    parser.add_argument(
        '-s', '--fontsize',
        nargs='?',
        type=float,
        action='store',
        default=None,
        help=('Set a fontsize to display emoji. '
              + 'If not specified, the fontsize is read from the config file. '
              + 'If that fails 24 is used as a fall back fontsize. '
              + 'default: "%(default)s"'))
    parser.add_argument(
        '-m', '--modal',
        action='store_true',
        default=False,
        help=('Make the window of emoji-picker modal. '
              + 'default: %(default)s'))
    parser.add_argument(
        '-a', '--all',
        action='store_true',
        default=False,
        help=('Load all Unicode characters. '
              + 'Makes all Unicode characters accessible, '
              + 'even normal letters. '
              + 'Slows the search down and is usually not needed. '
              + 'default: %(default)s'))
    parser.add_argument(
        '--fallback',
        nargs='?',
        type=int,
        action='store',
        default=None,
        help=('Whether to use fallback fonts when rendering emoji. '
              + 'If not 0, pango will use fallback fonts as necessary. '
              + 'If 0, pango will use only glyphs from '
              + 'the closest matching font on the system. No fallback '
              + 'will be done to other fonts on the system that '
              + 'might contain the glyhps needed to render an emoji. '
              + 'default: "%(default)s"')
        )
    parser.add_argument(
        '--emoji_unicode_min',
        nargs='?',
        type=str,
        action='store',
        default='1.0',
        help=('Load only emoji which were added to Unicode '
              + 'not earlier than this Unicode version. '
              + 'default: %(default)s'))
    # Guess current Unicode version:
    unicode_versions = (
        ('20180605', '11.0'),
        ('20190701', '12.0'),
        ('20200701', '13.0'),
    )
    current_date = time.strftime('%Y%m%d')
    current_unicode_version = 10.0
    for (date, version) in unicode_versions:
        if current_date > date:
            current_unicode_version = version
    parser.add_argument(
        '--emoji_unicode_max',
        nargs='?',
        type=str,
        action='store',
        default=current_unicode_version,
        help=('Load only emoji which were added to Unicode '
              + 'not later than this Unicode version. '
              + 'default: %(default)s'))
    parser.add_argument(
        '-d', '--debug',
        action='store_true',
        default=False,
        help=('Print some debug output to stdout. '
              + 'default: %(default)s'))
    parser.add_argument(
        '--version',
        action='store_true',
        default=False,
        help=('Output version information and exit. '
              + 'default: %(default)s'))
    return parser.parse_args()

_ARGS = parse_args()

class EmojiPickerUI(Gtk.Window):
    '''
    User interface of the emoji picker
    '''
    def __init__(self,
                 languages=('en_US',),
                 modal=False,
                 unicode_data_all=False,
                 emoji_unicode_min=1.0,
                 emoji_unicode_max=100.0,
                 font=None,
                 fontsize=None,
                 fallback=None):
        Gtk.Window.__init__(self, title='🚀 ' + _('Emoji Picker'))

        self.set_name('EmojiPicker')
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(
            b'''
            #EmojiPicker {
            }
            flowbox {
            }
            flowboxchild {
                border-style: groove;
                border-width: 0.05px;
            }
            row { /* This is for listbox rows */
                border-style: groove;
                border-width: 0.05px;
            }
            .font {
                padding: 2px 2px;
            }
            ''')
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # https://tronche.com/gui/x/icccm/sec-4.html#WM_CLASS
        # gnome-shell seems to use the first argument of set_wmclass()
        # to find the .desktop file.  If the .desktop file can be
        # found, the name shown by gnome-shell in the top bar comes
        # from that .desktop file and the icon to show is also read
        # from that .desktop file. If the .desktop file cannot be
        # found, the second argument of set_wmclass() is shown by
        # gnome-shell in the top bar.
        #
        # It only works like this when gnome-shell runs under Xorg
        # though, under Wayland things are different.
        self.set_wmclass('emoji-picker', 'Emoji Picker')
        self.set_default_size(700, 400)
        self._modal = modal
        self.set_modal(self._modal)
        available_fonts = self._list_font_names()
        self._font = 'emoji'
        if available_fonts:
            self._font = available_fonts[0]
        self._fontsize = 24
        self._fallback = True
        self._font_popover = None
        self._font_popover_scroll = None
        self._font_popover_listbox = None
        self._options_file = os.path.join(
            itb_util.xdg_save_data_path('emoji-picker'),
            'options')
        self._read_options()
        if not font is None:
            self._font = font
        if not fontsize is None:
            self._fontsize = fontsize
        if not fallback is None:
            self._fallback = bool(fallback)
        self._save_options()
        self.connect('destroy-event', self.on_destroy_event)
        self.connect('delete-event', self.on_delete_event)
        self.connect('key-press-event', self.on_main_window_key_press_event)
        self._languages = languages
        self._emoji_unicode_min = emoji_unicode_min
        self._emoji_unicode_max = emoji_unicode_max
        self._unicode_data_all = unicode_data_all
        self._emoji_matcher = itb_emoji.EmojiMatcher(
            languages=self._languages,
            unicode_data_all=self._unicode_data_all,
            emoji_unicode_min=self._emoji_unicode_min,
            emoji_unicode_max=self._emoji_unicode_max,
            variation_selector='emoji')
        self._gettext_translations = {}
        for language in itb_util.expand_languages(self._languages):
            mo_file = gettext.find(DOMAINNAME, languages=[language])
            if (mo_file
                    and
                    '/' + language  + '/LC_MESSAGES/' + DOMAINNAME + '.mo'
                    in mo_file):
                # Get the gettext translation instance only if a
                # translation file for this *exact* language was
                # found.  Ignore it if only a fallback was found. For
                # example, if “de_DE” was requested and only “de” was
                # found, ignore it.
                try:
                    self._gettext_translations[language] = gettext.translation(
                        DOMAINNAME, languages=[language])
                except (OSError, ):
                    self._gettext_translations[language] = None
            else:
                self._gettext_translations[language] = None

        self._currently_selected_label = None
        self._candidates_invalid = False
        self._query_string = ''
        self._emoji_selected_popover = None
        self._emoji_info_popover = None
        self._skin_tone_popover = None
        self._skin_tone_selected_popover = None

        self._main_container = Gtk.VBox()
        self.add(self._main_container)
        self._header_bar = Gtk.HeaderBar()
        self._header_bar.set_hexpand(True)
        self._header_bar.set_vexpand(False)
        self._header_bar.set_show_close_button(True)
        self._main_menu_button = Gtk.Button.new_from_icon_name(
            'open-menu-symbolic', Gtk.IconSize.BUTTON)
        self._header_bar.pack_start(self._main_menu_button)
        self._main_menu_popover = Gtk.Popover()
        self._main_menu_popover.set_relative_to(self._main_menu_button)
        self._main_menu_popover.set_position(Gtk.PositionType.BOTTOM)
        self._main_menu_popover_vbox = Gtk.VBox()
        self._main_menu_clear_recently_used_button = Gtk.Button(
            label=_('Clear recently used'))
        self._main_menu_clear_recently_used_button.connect(
            'clicked', self.on_clear_recently_used_button_clicked)
        self._main_menu_popover_vbox.pack_start(
            self._main_menu_clear_recently_used_button, False, False, 0)
        if not self._modal:
            self._main_menu_about_button = Gtk.Button(label=_('About'))
            self._main_menu_about_button.connect(
                'clicked', self.on_about_button_clicked)
            self._main_menu_popover_vbox.pack_start(
                self._main_menu_about_button, False, False, 0)
        self._main_menu_quit_button = Gtk.Button(label=_('Quit'))
        self._main_menu_quit_button.connect('clicked', self.on_delete_event)
        self._main_menu_popover_vbox.pack_start(
            self._main_menu_quit_button, False, False, 0)
        self._main_menu_popover.add(self._main_menu_popover_vbox)
        self._main_menu_button.connect(
            'clicked', self.on_main_menu_button_clicked)
        self._toggle_search_button = Gtk.Button.new_from_icon_name(
            'edit-find-symbolic', Gtk.IconSize.BUTTON)
        self._toggle_search_button.set_tooltip_text(
            _('Search for emoji'))
        self._toggle_search_button.connect(
            'clicked', self.on_toggle_search_button_clicked)
        self._header_bar.pack_start(self._toggle_search_button)
        self._font_button = Gtk.Button()
        self._font_button.set_always_show_image(True)
        self._font_button.set_image_position(Gtk.PositionType.LEFT)
        self._font_button.set_image(
            Gtk.Image.new_from_icon_name(
                'preferences-desktop-font', Gtk.IconSize.BUTTON))
        self._font_button.set_label(self._font)
        self._font_button.set_tooltip_text(
            _('Set the font to display emoji'))
        self._font_button.connect(
            'clicked', self.on_font_button_clicked)
        self._header_bar.pack_start(self._font_button)
        self._fontsize_spin_button = Gtk.SpinButton()
        self._fontsize_spin_button.set_numeric(True)
        self._fontsize_spin_button.set_can_focus(True)
        self._fontsize_spin_button.set_tooltip_text(
            _('Set font size'))
        self._fontsize_spin_button.connect(
            'grab-focus', self.on_fontsize_spin_button_grab_focus)
        self._fontsize_adjustment = Gtk.Adjustment()
        self._fontsize_adjustment.set_lower(1)
        self._fontsize_adjustment.set_upper(10000)
        self._fontsize_adjustment.set_value(self._fontsize)
        self._fontsize_adjustment.set_step_increment(1)
        self._fontsize_spin_button.set_adjustment(self._fontsize_adjustment)
        self._fontsize_adjustment.connect(
            'value-changed', self.on_fontsize_adjustment_value_changed)
        self._header_bar.pack_start(self._fontsize_spin_button)
        self._fallback_check_button = Gtk.CheckButton()
        # Translators: This is a checkbox which enables or disables
        # the pango font fallback. If font fallback is off, only the
        # font selected in the font menu is used to display emoji
        # (if possible, this may not always work, sometimes other fonts
        # may be used even if font fallback is off).
        # If font fallback is on, other fonts will be tried for emoji
        # or parts of emoji sequences which cannot be displayed in the
        # selected font.
        self._fallback_check_button.set_label(_('Fallback'))
        self._fallback_check_button.set_tooltip_text(
            _('Whether to use font fallback for emoji or parts of emoji '
              + 'sequences which cannot be displayed using the '
              + 'selected font.'))
        self._fallback_check_button.set_active(self._fallback)
        self._fallback_check_button.connect(
            'toggled', self.on_fallback_check_button_toggled)
        self._header_bar.pack_start(self._fallback_check_button)
        self._spinner = Gtk.Spinner()
        self._header_bar.pack_end(self._spinner)
        self.set_titlebar(self._header_bar)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_hexpand(False)
        self._search_entry.set_vexpand(False)
        self._search_entry.set_can_focus(True)
        self._search_entry.grab_focus_without_selecting()
        self._search_bar = Gtk.SearchBar()
        self._search_bar.set_hexpand(False)
        self._search_bar.set_vexpand(False)
        self._search_bar.set_show_close_button(False)
        self._search_bar.set_search_mode(False) # invisible by default
        self._search_bar.add(self._search_entry)
        self._search_bar.connect_entry(self._search_entry)
        self._search_entry.connect(
            'search-changed', self.on_search_entry_search_changed)
        self._search_entry.connect(
            'grab-focus', self.on_search_entry_grab_focus)

        self._browse_paned = Gtk.HPaned()
        self._main_container.pack_start(self._browse_paned, True, True, 0)
        self._browse_paned.set_wide_handle(True)
        self._browse_paned.set_hexpand(True)
        self._browse_paned.set_vexpand(True)

        self._browse_treeview_scroll = Gtk.ScrolledWindow()
        self._browse_treeview = Gtk.TreeView()
        self._browse_treeview.set_activate_on_single_click(True)
        self._browse_treeview.set_vexpand(True)
        self._browse_treeview.get_selection().connect(
            'changed', self.on_label_selected)
        self._browse_treeview.connect(
            'row-activated', self.on_row_activated)
        self._browse_treeview_scroll.add(self._browse_treeview)

        self._flowbox_scroll = Gtk.ScrolledWindow()
        self._flowbox_scroll.set_hexpand(True)
        self._flowbox_scroll.set_vexpand(True)
        self._flowbox_scroll.set_capture_button_press(False)
        self._flowbox_scroll.set_kinetic_scrolling(False)
        self._flowbox_scroll.set_overlay_scrolling(True)
        self._flowbox = Gtk.FlowBox()
        self._flowbox_scroll.add(self._flowbox)
        self._long_press_gestures = []

        self._left_pane = Gtk.VBox()
        self._left_pane.set_homogeneous(False)
        self._left_pane.pack_start(self._search_bar, False, False, 0)
        self._left_pane.pack_start(self._browse_treeview_scroll, True, True, 0)

        self._right_pane = Gtk.VBox()
        self._right_pane.pack_start(self._flowbox_scroll, True, True, 0)

        self._browse_paned.pack1(
            self._left_pane, resize=True, shrink=True)
        self._browse_paned.pack2(
            self._right_pane, resize=True, shrink=True)

        self._browse_treeview_model = Gtk.TreeStore(str, str, str, str)
        self._browse_treeview.set_model(self._browse_treeview_model)

        self._recently_used_label = '🕒 ' + _('Recently used')
        dummy_recent_iter = self._browse_treeview_model.append(
            None,
            [self._recently_used_label, '', '', self._recently_used_label])

        self._recently_used_emoji = {}
        self._recently_used_emoji_file = os.path.join(
            itb_util.xdg_save_data_path('emoji-picker'),
            'recently-used')
        self._recently_used_emoji_maximum = 100
        self._read_recently_used()

        self._emoji_by_label = self._emoji_matcher.emoji_by_label()
        expanded_languages = itb_util.expand_languages(self._languages)
        # 'en_001' and 'es_419' are not very useful in the treeview to
        # browse the languages, remove them from the list:
        expanded_languages = [
            lang
            for lang in expanded_languages
            if lang not in ('en_001', 'es_419')]
        first_language_with_categories = -1
        number_of_empty_languages = 0
        for language_index, language in enumerate(expanded_languages):
            language_empty = True
            if language in self._emoji_by_label:
                language_iter = self._browse_treeview_model.append(
                    None, [language, '', '', ''])
                if self._add_label_key_to_model(
                        'categories',
                        self._translate_key('Categories', language),
                        language, language_iter):
                    language_empty = False
                    if first_language_with_categories < 0:
                        first_language_with_categories = (
                            language_index - number_of_empty_languages)
                if self._add_label_key_to_model(
                        'ucategories',
                        self._translate_key('Unicode categories', language),
                        language, language_iter):
                    language_empty = False
                if self._add_label_key_to_model(
                        'keywords',
                        self._translate_key('Keywords', language),
                        language, language_iter):
                    language_empty = False
                if language_empty:
                    self._browse_treeview_model.remove(language_iter)
            if language_empty:
                number_of_empty_languages += 1

        if _ARGS.debug:
            sys.stdout.write(
                'expanded_languages  = %s\n'
                %itb_util.expand_languages(self._languages)
                + 'first_language_with_categories = %s\n'
                %first_language_with_categories
                + 'number_of_empty_languages = %s\n'
                %number_of_empty_languages)

        self._browse_treeview.append_column(
            Gtk.TreeViewColumn(
                'Browse', Gtk.CellRendererText(), text=0))
        self._browse_treeview.set_headers_visible(False)
        self._browse_treeview.collapse_all()
        if first_language_with_categories >= 0:
            # add one to take the “Recently used” entry into account:
            first_path_component = first_language_with_categories + 1
            self._browse_treeview.expand_row(
                Gtk.TreePath([first_path_component]), False)
            self._browse_treeview.expand_row(
                Gtk.TreePath([first_path_component, 0]), False)
            self._browse_treeview.set_cursor(
                Gtk.TreePath([first_path_component, 0, 0]),
                self._browse_treeview.get_column(0))

        self._browse_treeview.columns_autosize()

        self.show_all()

        (dummy_minimum_width_search_entry,
         natural_width_search_entry) = self._search_entry.get_preferred_width()
        (dummy_minimum_width_search_bar,
         natural_width_search_bar) = self._search_bar.get_preferred_width()
        if _ARGS.debug:
            sys.stdout.write(
                'natural_width_search_entry = %s '
                %natural_width_search_entry
                + 'natural_width_search_bar = %s\n'
                %natural_width_search_bar)
        self._browse_paned.set_position(natural_width_search_bar)

        self._selection_clipboard = Gtk.Clipboard.get(
            Gdk.SELECTION_CLIPBOARD)
        self._selection_primary = Gtk.Clipboard.get(
            Gdk.SELECTION_PRIMARY)

    def _busy_start(self):
        '''
        Show that this program is busy
        '''
        self._spinner.start()
        # self.get_root_window().set_cursor(Gdk.Cursor(Gdk.CursorType.WATCH))
        # Gdk.flush()

    def _busy_stop(self):
        '''
        Stop showing that this program is busy
        '''
        self._spinner.stop()
        # self.get_root_window().set_cursor(Gdk.Cursor(Gdk.CursorType.ARROW))

    def _variation_selector_normalize_for_font(self, emoji):
        '''
        Normalize the variation selectors in the emoji sequence.

        Returns a new emoji sequences with variation selectors added
        or removed as appropriate for the current font.

        :param emoji: The emoji
        :type emoji: String
        :rtype: String
        '''
        if self._font == 'text' or self._font.lower() == 'symbola':
            return self._emoji_matcher.variation_selector_normalize(
                emoji, 'text')
        if self._font == 'unqualified':
            return self._emoji_matcher.variation_selector_normalize(
                emoji, '')
        return self._emoji_matcher.variation_selector_normalize(
            emoji, 'emoji')

    def _browse_treeview_unselect_all(self):
        '''
        Unselect everything in the treeview for browsing the categories
        '''
        self._browse_treeview.get_selection().unselect_all()
        self._currently_selected_label = None

    def _add_label_key_to_model(
            self, label_key, label_key_display, language, language_iter):
        if not label_key in self._emoji_by_label[language]:
            return False
        labels = self._sort_labels(
            self._emoji_by_label[language][label_key],
            language)
        if not labels:
            return False
        label_key_iter = self._browse_treeview_model.append(
            language_iter, [label_key_display, '', '', ''])
        for label in labels:
            number_of_emoji = len(
                self._emoji_by_label[language][label_key][label])
            self._browse_treeview_model.append(
                label_key_iter,
                [label + ' ' + str(number_of_emoji),
                 language, label_key, label])
        return True

    def _sort_labels(self, labels, language): # pylint: disable=no-self-use
        return sorted(
            labels,
            key=lambda x: (
                # For Japanese and Chinese: sort Chinese
                # characters before Hiragana and Latin:
                (language.startswith('ja') or language.startswith('zh'))
                and not unicodedata.name(x[0]).startswith('CJK'),
                language.startswith('ja')
                and not unicodedata.name(x[0]).startswith('HIRAGANA'),
                # sort Digits after non Digits:
                unicodedata.name(x[0]).startswith('DIGIT'),
                x.lower()))

    def _translate_key(self, key, language='en'):
        dummy_keys_to_translate = [
            N_('Categories'),
            N_('Unicode categories'),
            N_('Keywords'),
        ]
        if self._gettext_translations[language]:
            return self._gettext_translations[language].gettext(key)
        return key

    def _emoji_descriptions(self, emoji):
        '''
        Return a description of the emoji

        The description shows the Unicode codepoint(s) of the emoji
        and the names of the emoji in all languages used.

        :param emoji: The emoji
        :type emoji: String
        :rtype: List of strings
        '''
        descriptions = []
        descriptions.append(
            ' '.join(['U+%X' %ord(character) for character in emoji]))
        for language in itb_util.expand_languages(self._languages):
            names = self._emoji_matcher.names(emoji, language=language)
            description = '<b>%s</b>' %language
            description_empty = True
            if names:
                description += '\n' + html.escape(', '.join(names))
                description_empty = False
            keywords = self._emoji_matcher.keywords(emoji, language=language)
            if keywords:
                description += (
                    '\n' + self._translate_key('Keywords', language) + ': '
                    + html.escape(', '.join(keywords)))
                description_empty = False
            categories = self._emoji_matcher.categories(
                emoji, language=language)
            if categories:
                description += (
                    '\n' + self._translate_key('Categories', language) + ': '
                    + html.escape(', '.join(categories)))
                description_empty = False
            if not description_empty:
                descriptions.append(description)
        fonts_description = _('Fonts used to render this emoji:')
        for text, font_family in itb_pango.get_fonts_used_for_text(
                self._font + ' ' + str(self._fontsize), emoji,
                fallback=self._fallback):
            fonts_description += '\n'
            code_points = ''
            for char in text:
                code_points += ' U+%X' %ord(char)
            fonts_description += (
                '<span font="%s" fallback="%s" >'
                %(self._font, str(self._fallback).lower())
                + text + '</span>'
                + '<span fallback="false">%s</span>' %code_points)
            fonts_description += ': ' + font_family
        descriptions.append(fonts_description)
        if self._emoji_matcher.unicode_version(emoji):
            descriptions.append(
                _('Unicode Version:') + ' '
                + self._emoji_matcher.unicode_version(emoji))
        if _ARGS.debug:
            descriptions.append(
                'emoji_order = %s' %self._emoji_matcher.emoji_order(emoji))
            descriptions.append(
                'cldr_order = %s' %self._emoji_matcher.cldr_order(emoji))
            descriptions.append(
                'Emoji properties from unicode.org:' + '\n'
                + ', '.join(self._emoji_matcher.properties(emoji)))
        return descriptions

    def _emoji_label_set_tooltip( # pylint: disable=no-self-use
            self, emoji, label):
        '''
        Set the tooltip for a label in the flowbox which shows an emoji

        :param emoji: The emoji
        :type emoji: String
        :param label: The label used to show the emoji
        :type label: Gtk.Label object
        '''
        tooltip_text = _('Left click to copy') + '\n'
        if len(self._emoji_matcher.skin_tone_variants(emoji)) > 1:
            tooltip_text += (
                _('Long press or middle click for skin tones')  + '\n')
        tooltip_text += _('Right click for info')
        label.set_tooltip_text(tooltip_text)

    def _clear_flowbox(self):
        '''
        Clear the contents of the flowbox
        '''
        for child in self._flowbox_scroll.get_children():
            self._flowbox_scroll.remove(child)
        self._flowbox = Gtk.FlowBox()
        self._flowbox.get_style_context().add_class('view')
        self._flowbox_scroll.add(self._flowbox)
        self._flowbox.set_valign(Gtk.Align.START)
        self._flowbox.set_min_children_per_line(1)
        self._flowbox.set_max_children_per_line(100)
        self._flowbox.set_row_spacing(0)
        self._flowbox.set_column_spacing(0)
        self._flowbox.set_activate_on_single_click(True)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.set_can_focus(False)
        self._flowbox.set_homogeneous(False)
        self._flowbox.set_hexpand(False)
        self._flowbox.set_vexpand(False)
        self._flowbox.connect('child-activated', self.on_emoji_selected)
        for long_press_gesture in self._long_press_gestures:
            # disconnecting is necessary to avoid warnings to stdout:
            for ids in long_press_gesture[1]:
                long_press_gesture[0].disconnect(ids)
        self._long_press_gestures = []

    def _fill_flowbox_browse(self):
        '''
        Fill the flowbox with content according to the currently
        selected label in the browsing treeview.
        '''
        (language, label_key, label) = self._currently_selected_label
        if _ARGS.debug:
            sys.stdout.write(
                '_fill_flowbox_browse() '
                + 'language = %s label_key = %s label = %s\n'
                %(language, label_key, label))
        emoji_list = []
        is_recently_used = False
        sorted_recently_used = self._sorted_recently_used()
        if label == self._recently_used_label:
            is_recently_used = True
            emoji_list = sorted_recently_used
        if (language in self._emoji_by_label
                and label_key in self._emoji_by_label[language]
                and label in  self._emoji_by_label[language][label_key]):
            emoji_list = self._emoji_by_label[language][label_key][label]

        self._header_bar.set_title(label)
        if label:
            self._header_bar.set_subtitle(str(len(emoji_list)))
        else:
            self._header_bar.set_subtitle('')

        if not emoji_list:
            self._busy_stop()
            return

        for emoji in emoji_list:
            while Gtk.events_pending():
                Gtk.main_iteration()
            emoji = self._variation_selector_normalize_for_font(emoji)
            if not is_recently_used:
                skin_tone_variants = self._emoji_matcher.skin_tone_variants(
                    emoji)
                if len(skin_tone_variants) > 1:
                    # For an emoji which can take a skin tone modifier,
                    # replace it by the most recently used variant.
                    # If no variant has been recently used, leave
                    # the base emoji as it is:
                    recently_used_index = len(sorted_recently_used)
                    for skin_tone_variant in skin_tone_variants:
                        if skin_tone_variant in sorted_recently_used:
                            recently_used_index = min(
                                recently_used_index,
                                sorted_recently_used.index(skin_tone_variant))
                    if recently_used_index < len(sorted_recently_used):
                        emoji = sorted_recently_used[recently_used_index]
            label = Gtk.Label()
            # Make font for emoji large using pango markup
            text = (
                '<span font="%s %s" fallback="%s">'
                %(self._font, self._fontsize, str(self._fallback).lower())
                + html.escape(emoji)
                + '</span>')
            if itb_emoji.is_invisible(emoji):
                text += (
                    '<span fallback="false" font="%s">'
                    %(self._fontsize / 2)
                    + ' U+%X ' %ord(emoji)
                    + self._emoji_matcher.name(emoji)
                    + '</span>')
            label.set_text(text)
            label.set_use_markup(True)
            label.set_can_focus(False)
            label.set_selectable(False)
            label.set_hexpand(False)
            label.set_vexpand(False)
            label.set_xalign(0.5)
            label.set_yalign(0.5)
            # Gtk.Align.FILL, Gtk.Align.START, Gtk.Align.END,
            # Gtk.Align.CENTER, Gtk.Align.BASELINE
            label.set_halign(Gtk.Align.FILL)
            label.set_valign(Gtk.Align.FILL)
            margin = 0
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._emoji_label_set_tooltip(emoji, label)
            event_box = Gtk.EventBox()
            event_box.set_above_child(True)
            event_box.set_can_focus(False)
            event_box.add(label)
            event_box.add_events(Gdk.EventType.BUTTON_PRESS)
            event_box.add_events(Gdk.EventType.BUTTON_RELEASE)
            event_box.connect(
                'button-press-event',
                self.on_flowbox_event_box_button_press)
            event_box.connect(
                'button-release-event',
                self.on_flowbox_event_box_button_release)
            long_press_gesture = Gtk.GestureLongPress.new(event_box)
            long_press_gesture.set_touch_only(False)
            long_press_gesture.set_propagation_phase(
                Gtk.PropagationPhase.CAPTURE)
            id_pressed = long_press_gesture.connect(
                'pressed',
                self.on_flowbox_event_box_long_press_pressed, event_box)
            id_begin = long_press_gesture.connect(
                'begin',
                self.on_flowbox_event_box_long_press_begin)
            id_cancel = long_press_gesture.connect(
                'cancel',
                self.on_flowbox_event_box_long_press_cancel)
            id_cancelled = long_press_gesture.connect(
                'cancelled',
                self.on_flowbox_event_box_long_press_cancelled)
            self._long_press_gestures.append(
                (long_press_gesture,
                 (id_pressed,
                  id_begin,
                  id_cancel,
                  id_cancelled)))
            self._flowbox.insert(event_box, -1)

        for child in self._flowbox.get_children():
            child.set_can_focus(False)

        self.show_all()
        self._busy_stop()

    def _read_options(self):
        '''
        Read the options for 'font' and 'fontsize' from  a file
        '''
        options_dict = {}
        if os.path.isfile(self._options_file):
            try:
                options_dict = eval(open(
                    self._options_file,
                    mode='r',
                    encoding='UTF-8').read())
            except (PermissionError, SyntaxError, IndentationError):
                import traceback
                traceback.print_exc()
            except Exception as dummy_exception:
                import traceback
                traceback.print_exc()
            else: # no exception occured
                if _ARGS.debug:
                    sys.stdout.write(
                        'File %s has been read and evaluated.\n'
                        %self._options_file)
            finally: # executes always
                if not isinstance(options_dict, dict):
                    if _ARGS.debug:
                        sys.stdout.write(
                            'Not a dict: repr(options_dict) = %s\n'
                            %options_dict)
                    options_dict = {}
        if ('font' in options_dict
                and isinstance(options_dict['font'], str)):
            self._font = options_dict['font']
            if self._font == '':
                self._font = 'emoji'
        if ('fontsize' in options_dict
                and (isinstance(options_dict['fontsize'], (int, float)))):
            self._fontsize = options_dict['fontsize']
        if ('fallback' in options_dict
                and (isinstance(options_dict['fallback'], bool))):
            self._fallback = options_dict['fallback']

    def _save_options(self):
        '''
        Save the options for 'font' and 'fontsize' to a file
        '''
        options_dict = {
            'font': self._font,
            'fontsize': self._fontsize,
            'fallback': self._fallback,
            }
        with open(self._options_file,
                  mode='w',
                  encoding='UTF-8') as options_file:
            options_file.write(repr(options_dict))
            options_file.write('\n')

    def _sorted_recently_used(self):
        '''
        Return a sorted list of recently used emoji
        '''
        return sorted(self._recently_used_emoji,
                      key=lambda x: (
                          - self._recently_used_emoji[x]['time'],
                          - self._recently_used_emoji[x]['count']))

    def _read_recently_used(self):
        '''
        Read the recently use emoji from a file
        '''
        recently_used_emoji = {}
        if os.path.isfile(self._recently_used_emoji_file):
            try:
                recently_used_emoji = eval(open(
                    self._recently_used_emoji_file,
                    mode='r',
                    encoding='UTF-8').read())
            except (PermissionError, SyntaxError, IndentationError):
                import traceback
                traceback.print_exc()
            except Exception as dummy_exception:
                import traceback
                traceback.print_exc()
            else: # no exception occured
                if _ARGS.debug:
                    sys.stdout.write(
                        'File %s has been read and evaluated.\n'
                        %self._recently_used_emoji_file)
            finally: # executes always
                if not isinstance(recently_used_emoji, dict):
                    if _ARGS.debug:
                        sys.stdout.write(
                            'Not a dict: '
                            + 'repr(recently_used_emoji) = %s\n'
                            %recently_used_emoji)
                    recently_used_emoji = {}
        self._recently_used_emoji = {}
        for emoji, value in recently_used_emoji.items():
            # add or remove vs16 according to the current setting:
            if emoji:
                self._recently_used_emoji[
                    self._variation_selector_normalize_for_font(emoji)] = value
        if not self._recently_used_emoji:
            self._init_recently_used()
        self._cleanup_recently_used()

    def _cleanup_recently_used(self):
        '''
        Reduces the size of the recently used dictionary
        if it has become too big.
        '''
        if len(self._recently_used_emoji) > self._recently_used_emoji_maximum:
            for emoji in sorted(
                    self._recently_used_emoji,
                    key=lambda x: (
                        - self._recently_used_emoji[x]['time'],
                        - self._recently_used_emoji[x]['count'],
                    ))[self._recently_used_emoji_maximum:]:
                del self._recently_used_emoji[emoji]

    def _init_recently_used(self):
        '''
        Initialize the recently used emoji

        - Make the the recently used emoji empty
        - Save it to disk
        - Clear the flowbox if it is currently showing the recently used
        '''
        self._recently_used_emoji = {}
        self._save_recently_used_emoji()
        if (self._currently_selected_label ==
                ('', '', self._recently_used_label)):
            self._clear_flowbox()

    def on_clear_recently_used_button_clicked(self, _button):
        '''
        :param _button: The “Clear recently used” button
        :type _button: Gtk.Button object
        '''
        if _ARGS.debug:
            sys.stdout.write('on_clear_recently_used_button_clicked()\n')
        if GTK_VERSION >= (3, 22, 0):
            self._main_menu_popover.popdown()
        self._main_menu_popover.hide()
        self._init_recently_used()

    def _add_to_recently_used(self, emoji):
        '''
        Adds an emoji to the resently used dictionary.

        :param emoji: The emoji string
        :type emoji: String
        '''
        if emoji in self._recently_used_emoji:
            self._recently_used_emoji[emoji]['count'] += 1
            self._recently_used_emoji[emoji]['time'] = time.time()
        else:
            self._recently_used_emoji[emoji] = {
                'count': 1, 'time': time.time()}
        self._cleanup_recently_used()
        # Better save always, on_delete_event() is not called
        # when the program is stopped using Control+C
        self._save_recently_used_emoji()

    def _save_recently_used_emoji(self):
        '''
        Save the list of recently used emoji
        '''
        with open(self._recently_used_emoji_file,
                  mode='w',
                  encoding='UTF-8') as recents_file:
            recents_file.write(repr(self._recently_used_emoji))
            recents_file.write('\n')

    def _set_clipboards(self, text):
        '''
        Set the clipboard and the primary selection to “text”

        :param text: The text to set the clipboards to
        :type text: String
        '''
        self._selection_clipboard.set_text(text, -1)
        self._selection_primary.set_text(text, -1)
        # Store the current clipboard data somewhere so that
        # it will stay around after the application has quit:
        self._selection_clipboard.store()
        self._selection_primary.store() # Does not work.

    def _show_concise_emoji_description_in_header_bar(self, emoji):
        '''
        Show a concise description of an emoji in the header bar
        of the program.

        :param emoji: The emoji for which a description should be
                      shown in the header bar.
        :type emoji: String
        '''
        self._header_bar.set_title(emoji)
        self._header_bar.set_subtitle('')
        # Display the names of the emoji in the first language
        # where names are available in the header bar title:
        for language in itb_util.expand_languages(self._languages):
            names = self._emoji_matcher.names(emoji, language=language)
            if names:
                self._header_bar.set_title(emoji + ' ' + ', '.join(names))
                break
        # Display the keywords of the emoji in the first language
        # where keywords are available in the header bar subtitle:
        for language in itb_util.expand_languages(self._languages):
            keywords = self._emoji_matcher.keywords(emoji, language=language)
            if keywords:
                self._header_bar.set_subtitle(
                    self._translate_key('Keywords', language) + ': '
                    + ', '.join(keywords))
                break

    def _print_profiling_information(self):
        '''
        Print some profiling information to stdout.
        '''
        PROFILE.disable()
        stats = pstats.Stats(PROFILE)
        stats.strip_dirs()
        stats.sort_stats('cumulative')
        stats.print_stats('emoji_picker', 25)
        stats.print_stats('itb_emoji', 25)

    def on_delete_event(self, *_args):
        '''
        The window has been deleted, probably by the window manager.
        '''
        self._save_recently_used_emoji()
        if _ARGS.debug:
            self._print_profiling_information()
        Gtk.main_quit()

    def on_destroy_event(self, *_args):
        '''
        The window has been destroyed.
        '''
        self._save_recently_used_emoji()
        if _ARGS.debug:
            self._print_profiling_information()
        Gtk.main_quit()

    def on_main_window_key_press_event(self, _window, event_key):
        '''
        Some key has been typed into the main window

        :param _window: The main window
        :type _window: Gtk.Window object
        :param event_key:
        :type event_key: Gdk.EventKey object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_main_window_key_press_event() '
                + 'keyval = %s\n'
                %event_key.keyval)
        if self._fontsize_spin_button.has_focus():
            if _ARGS.debug:
                sys.stdout.write(
                    'on_main_window_key_press_event(): '
                    + 'self._fontsize_spin_button has focus\n')
            # if the fontsize spin button has focus, we do not want
            # to take it away from there by popping up the search bar.
            return
        # https://developer.gnome.org/gdk3/stable/gdk3-Event-Structures.html#GdkEventKey
        # See /usr/include/gtk-3.0/gdk/gdkkeysyms.h for a list
        # of Gdk keycodes
        if (event_key.keyval in (
                Gdk.KEY_Tab,
                Gdk.KEY_Down, Gdk.KEY_KP_Down,
                Gdk.KEY_Up, Gdk.KEY_KP_Up,
                Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down,
                Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up)):
            self._search_bar.set_search_mode(False)
            return
        if not event_key.string:
            return
        self._search_bar.set_search_mode(True)
        self._search_bar.show_all()
        # The search entry needs to be realized to be able to
        # handle a key event. If it is not realized yet when
        # the key event arrives, one will get the message:
        #
        # Gtk-CRITICAL **: gtk_widget_event:
        # assertion 'WIDGET_REALIZED_FOR_EVENT (widget, event)' failed
        #
        # and the typed key will not appear in the search entry.
        #
        # The self._search_bar.show_all() realizes the search
        # entry, but only when the pending events are handled.
        # So we need to call Gtk.main_iteration() while events
        # are pending.
        #
        # But *only* if the search entry is not realized yet,
        # i.e. only if self._search_entry.get_window() returns “None”.
        # After the first key press it is realized and we must not do
        # this anymore. Continuing to handle the pending events here
        # when the search entry is already realized makes the keys
        # appear out of order in the search entry when typing
        # fast. For example, when typing “flow” fast one may get
        # “flwo”.
        if not self._search_entry.get_window():
            while Gtk.events_pending():
                Gtk.main_iteration()
        self._search_bar.handle_event(event_key)

    def on_about_button_clicked(self, _button):
        '''
        The “About” button has been clicked

        :param _button: The “About” button
        :type _button: Gtk.Button object
        '''
        if _ARGS.debug:
            sys.stdout.write('on_about_button_clicked()\n')
        if GTK_VERSION >= (3, 22, 0):
            self._main_menu_popover.popdown()
        self._main_menu_popover.hide()
        itb_util.ItbAboutDialog()

    def _fill_flowbox_with_search_results(self):
        '''
        Get the emoji candidates for the current query string
        and fill the flowbox with the results of the query.
        '''
        if _ARGS.debug:
            sys.stdout.write(
                '_fill_flowbox_with_search_results() query_string = %s\n'
                %self._query_string)
        candidates = self._emoji_matcher.candidates(
            self._query_string,
            match_limit=1000)

        self._browse_treeview_unselect_all()
        self._header_bar.set_title(_('Search Results'))
        self._header_bar.set_subtitle(str(len(candidates)))

        if not candidates:
            candidates = [('∅', _('Search produced empty result.'), 1)]

        for candidate in candidates:
            # Do *not* do
            #
            # while Gtk.events_pending():
            #     Gtk.main_iteration()
            #
            # here. Although this will keep the spinner turning, it
            # will have the side effect that further key events maybe
            # added to the query string while the flowbox is being
            # filled. But then the on_search_entry_search_changed()
            # callback will think that nothing needs to be done
            # because self._candidates_invalid is True already.
            emoji = self._variation_selector_normalize_for_font(candidate[0])
            name = candidate[1]
            dummy_score = candidate[2]
            label = Gtk.Label()
            # Make font for emoji large using pango markup
            label.set_text(
                '<span font="%s %s" fallback="%s">'
                %(self._font, self._fontsize, str(self._fallback).lower())
                + html.escape(emoji)
                + '</span>'
                + '<span font="%s">'
                %(self._fontsize / 2)
                + ' ' + html.escape(name)
                + '</span>')
            label.set_use_markup(True)
            label.set_can_focus(False)
            label.set_selectable(False)
            label.set_hexpand(False)
            label.set_vexpand(False)
            label.set_xalign(0)
            label.set_yalign(0.5)
            # Gtk.Align.FILL, Gtk.Align.START, Gtk.Align.END,
            # Gtk.Align.CENTER, Gtk.Align.BASELINE
            label.set_halign(Gtk.Align.FILL)
            label.set_valign(Gtk.Align.FILL)
            margin = 0
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._emoji_label_set_tooltip(emoji, label)
            event_box = Gtk.EventBox()
            event_box.set_can_focus(False)
            event_box.add(label)
            event_box.add_events(Gdk.EventType.BUTTON_PRESS)
            event_box.add_events(Gdk.EventType.BUTTON_RELEASE)
            event_box.connect(
                'button-press-event',
                self.on_flowbox_event_box_button_press)
            event_box.connect(
                'button-release-event',
                self.on_flowbox_event_box_button_release)
            long_press_gesture = Gtk.GestureLongPress.new(event_box)
            long_press_gesture.set_touch_only(False)
            long_press_gesture.set_propagation_phase(
                Gtk.PropagationPhase.CAPTURE)
            id_pressed = long_press_gesture.connect(
                'pressed',
                self.on_flowbox_event_box_long_press_pressed, event_box)
            id_begin = long_press_gesture.connect(
                'begin',
                self.on_flowbox_event_box_long_press_begin)
            id_cancel = long_press_gesture.connect(
                'cancel',
                self.on_flowbox_event_box_long_press_cancel)
            id_cancelled = long_press_gesture.connect(
                'cancelled',
                self.on_flowbox_event_box_long_press_cancelled)
            self._long_press_gestures.append(
                (long_press_gesture,
                 (id_pressed,
                  id_begin,
                  id_cancel,
                  id_cancelled)))
            self._flowbox.insert(event_box, -1)

        for child in self._flowbox.get_children():
            child.set_can_focus(False)

        self.show_all()
        self._candidates_invalid = False
        self._busy_stop()

    def on_fontsize_spin_button_grab_focus( # pylint: disable=no-self-use
            self, spin_button):
        '''
        Signal handler called when the spin button to change
        the font size grabs focus

        :param spin_button: The spin button to change the font size
        :type spin_button: Gtk.SpinButton object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_fontsize_spin_button_grab_focus() spin_button = %s\n'
                %repr(spin_button))
        spin_button.grab_focus_without_selecting()
        # The default signal handler would again select the contents
        # of the search entry. Therefore, we must prevent the default
        # signal handler from running:
        GObject.signal_stop_emission_by_name(spin_button, 'grab-focus')
        return True

    def on_search_entry_grab_focus( # pylint: disable=no-self-use
            self, search_entry):
        '''
        Signal handler called when the search entry grabs focus

        :param search_entry: The search entry
        :type search_entry: Gtk.SearchEntry object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_search_entry_grab_focus() search_entry = %s\n'
                %repr(search_entry))
        search_entry.grab_focus_without_selecting()
        # The default signal handler would again select the contents
        # of the search entry. Therefore, we must prevent the default
        # signal handler from running:
        GObject.signal_stop_emission_by_name(search_entry, 'grab-focus')
        return True

    def on_search_entry_search_changed(self, search_entry):
        '''
        Signal handler for changed text in the search entry

        :param widget: The search entry
        :type widget: Gtk.SearchEntry object
        '''
        query_string = search_entry.get_text()
        if _ARGS.debug:
            sys.stdout.write(
                'on_search_entry_search_changed() query_string = %s\n'
                %query_string)
        if not self._search_bar.get_search_mode():
            # If the text in the search entry changes while
            # the search bar is invisible, ignore it.
            return
        self._query_string = query_string
        if self._candidates_invalid:
            if _ARGS.debug:
                sys.stdout.write(
                    'on_search_entry_search_changed() '
                    + 'self._candidates_invalid = %s\n'
                    %self._candidates_invalid)
            return
        self._candidates_invalid = True
        self._clear_flowbox()
        self._busy_start()
        GLib.idle_add(self._fill_flowbox_with_search_results)

    def on_label_selected(self, selection):
        '''
        Signal handler for selecting a category in the list of categories

        :param selection: The selected row in the browsing treeview
        :type selection: Gtk.TreeSelection object
        '''
        (model, iterator) = selection.get_selected()
        if not iterator:
            return
        if _ARGS.debug:
            sys.stdout.write(
                'on_label_selected(): model[iterator] = %s\n'
                %model[iterator][:]
                + 'self._currently_selected_label = %s\n'
                %repr(self._currently_selected_label))
        self._search_bar.set_search_mode(False)
        self._browse_treeview.grab_focus()
        language = model[iterator][1]
        label_key = model[iterator][2]
        label = model[iterator][3]
        if self._currently_selected_label != (language, label_key, label):
            self._currently_selected_label = (language, label_key, label)
            self._clear_flowbox()
            self._busy_start()
            GLib.idle_add(self._fill_flowbox_browse)

    def on_row_activated( # pylint: disable=no-self-use
            self, treeview, treepath, column):
        '''Signal handler for activating a row in the browsing treeview

        :param treeview: The browsing treeview
        :type treeview: Gtk.TreeView object
        :param treepath: The path of the activated row in the browsing treeview
        :type treepath: Gtk.TreePath object
        :param column: The column of the activated row in the browsing treeview
        :type column: Gtk.TreeViewColumn object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_row_activated() %s %s %s\n'
                %(repr(treeview), repr(treepath), repr(column)))

    def _parse_emoji_and_name_from_text( # pylint: disable=no-self-use
            self, text):
        '''
        Parse the emoji and its name out of the text of a label

        :param text: The text with markup containing the emoji
                     and maybe its name
        :type text: String
        :rtype: A tuple of two strings of the form (emoji, name)
        '''
        emoji = ''
        name = ''
        pattern = re.compile(
            r'<span[^<]*?>(?P<emoji>[^<]+?)</span>'
            + r'(<span[^<]*?>(?P<name>[^<]+?)</span>)?')
        match = pattern.match(text)
        if match:
            emoji = html.unescape(match.group('emoji'))
        if match.group('name'):
            name = html.unescape(match.group('name'))
        if _ARGS.debug:
            sys.stdout.write(
                '_parse_emoji_and_name_from_text() '
                + 'text = %s emoji = %s name = %s\n'
                %(text, emoji, name))
        return (emoji, name)

    def _emoji_selected_popover_popdown(self):
        '''
        Hide the popover again which was shown when an emoji was selected
        '''
        if self._emoji_selected_popover:
            if GTK_VERSION >= (3, 22, 0):
                self._emoji_selected_popover.popdown()
            self._emoji_selected_popover.hide()
            self._emoji_selected_popover = None
        return False

    def _emoji_event_box_selected(self, event_box):
        '''
        Called when an event box containing an emoji
        was selected in the flowbox.

        The emoji is then copied to the clipboard and a popover
        pops up for a short time to notify the user that the emoji
        has been copied to the clipboard.

        :param event_box: The event box which contains the emoji
        :type event_box: Gtk.EventBox object
        '''
        # Use .get_label() instead of .get_text() to fetch the text
        # from the label widget including any embedded underlines
        # indicating mnemonics and Pango markup. The emoji is in
        # first <span>...</span>, and we want fetch only the emoji
        # here:
        text = event_box.get_child().get_label()
        if _ARGS.debug:
            sys.stdout.write("_emoji_event_box_selected() text = %s\n" %text)
        (emoji, name) = self._parse_emoji_and_name_from_text(text)
        if not emoji:
            return Gdk.EVENT_PROPAGATE
        self._show_concise_emoji_description_in_header_bar(emoji)
        self._set_clipboards(emoji)
        self._add_to_recently_used(emoji)
        self._emoji_selected_popover = Gtk.Popover()
        self._emoji_selected_popover.set_relative_to(event_box)
        self._emoji_selected_popover.set_position(Gtk.PositionType.TOP)
        if name:
            rectangle = Gdk.Rectangle()
            rectangle.x = 0
            rectangle.y = 0
            rectangle.width = self._fontsize * 1.5
            rectangle.height = self._fontsize * 1.5
            self._emoji_selected_popover.set_pointing_to(rectangle)
        label = Gtk.Label()
        label.set_text(_('Copied to clipboard!'))
        self._emoji_selected_popover.add(label)
        if GTK_VERSION >= (3, 22, 0):
            self._emoji_selected_popover.popup()
        self._emoji_selected_popover.show_all()
        GLib.timeout_add(500, self._emoji_selected_popover_popdown)

    def on_emoji_selected(self, _flowbox, flowbox_child):
        '''
        Signal handler for selecting an emoji in the flowbox
        via the flowbox selection

        Not called if long press gestures are used to show the
        skin tone popovers. In that case, emoji selection is handled
        in on_flowbox_event_box_button_release() instead.

        :param _flowbox: The flowbox displaying the Emoji
        :type _flowbox: Gtk.FlowBox object
        :param flowbox_child: The child object containing the selected emoji
        :type flowbox_child: Gtk.FlowBoxChild object
        '''
        if _ARGS.debug:
            sys.stdout.write("on_emoji_selected()\n")
        event_box = flowbox_child.get_child()
        self._emoji_event_box_selected(event_box)
        return Gdk.EVENT_PROPAGATE

    def on_main_menu_button_clicked(self, _button):
        '''
        The main menu button has been clicked

        :param _button: The main menu button
        :type _button: Gtk.Button object
        '''
        if _ARGS.debug:
            sys.stdout.write('on_main_menu_button_clicked()\n')
        if GTK_VERSION >= (3, 22, 0):
            self._main_menu_popover.popup()
        self._main_menu_popover.show_all()

    def on_toggle_search_button_clicked(self, _button):
        '''
        The search button in the header bar has been clicked

        :param _button: The search button
        :type  _button: Gtk.Button object
        '''
        if _ARGS.debug:
            sys.stdout.write('on_toggle_search_button_clicked()\n')
        self._search_bar.set_search_mode(
            not self._search_bar.get_search_mode())

    def _change_flowbox_font(self):
        '''
        Update the font and fontsize used in the current content
        of the flowbox.
        '''
        for flowbox_child in self._flowbox.get_children():
            label = flowbox_child.get_child().get_child()
            text = label.get_label()
            (emoji, name) = self._parse_emoji_and_name_from_text(text)
            if emoji:
                emoji = self._variation_selector_normalize_for_font(emoji)
                new_text = (
                    '<span font="%s %s" fallback="%s">'
                    %(self._font, self._fontsize, str(self._fallback).lower())
                    + html.escape(emoji)
                    + '</span>')
                if name:
                    new_text += (
                        '<span fallback="true" font="%s">'
                        %(self._fontsize / 2)
                        + html.escape(name)
                        + '</span>')
                label.set_text(new_text)
                label.set_use_markup(True)
        self.show_all()
        self._busy_stop()

    def _skin_tone_selected_popover_popdown(self):
        '''
        Hide the popover which was shown when an skin tone emoji
        was selected and the popover which showed the skin tone emoji.
        '''
        if self._skin_tone_selected_popover:
            if GTK_VERSION >= (3, 22, 0):
                self._skin_tone_selected_popover.popdown()
            self._skin_tone_selected_popover.hide()
            self._skin_tone_selected_popover = None
        if self._skin_tone_popover:
            if GTK_VERSION >= (3, 22, 0):
                self._skin_tone_popover.popdown()
            self._skin_tone_popover.hide()
            self._skin_tone_popover = None
        return False

    def on_skin_tone_selected(self, _flowbox, flowbox_child):
        '''
        Signal handler for selecting a skin tone emoji

        :param _flowbox: The flowbox displaying the skin tone emoji
        :type _flowbox: Gtk.FlowBox object
        :param flowbox_child: The child object containing the selected emoji
        :type flowbox_child: Gtk.FlowBoxChild object
        '''
        # Use .get_label() instead of .get_text() to fetch the text
        # from the label widget including any embedded underlines
        # indicating mnemonics and Pango markup. The emoji is in
        # first <span>...</span>, and we want fetch only the emoji
        # here:
        text = flowbox_child.get_child().get_label()
        if _ARGS.debug:
            sys.stdout.write('on_skin_tone_selected() text = %s\n' %text)
        (emoji, dummy_name) = self._parse_emoji_and_name_from_text(text)
        if not emoji:
            return
        self._show_concise_emoji_description_in_header_bar(emoji)
        self._set_clipboards(emoji)
        self._add_to_recently_used(emoji)
        self._skin_tone_selected_popover = Gtk.Popover()
        self._skin_tone_selected_popover.set_relative_to(
            flowbox_child.get_child())
        self._skin_tone_selected_popover.set_position(Gtk.PositionType.TOP)
        label = Gtk.Label()
        label.set_text(_('Copied to clipboard!'))
        self._skin_tone_selected_popover.add(label)
        if GTK_VERSION >= (3, 22, 0):
            self._skin_tone_selected_popover.popup()
        self._skin_tone_selected_popover.show_all()
        # When an emoji with a different skin tone is selected in a
        # skin tone popover opened in a browse flowbox (not a search
        # results flowbox), replace the original emoji which was used
        # to open the popover immediately.
        label = self._skin_tone_popover.get_relative_to().get_child()
        text = label.get_label()
        (old_emoji, old_name) = self._parse_emoji_and_name_from_text(text)
        if old_emoji and not old_name:
            # If the old emoji has a name, this is a line
            # in a search results flowbox and we do *not* want
            # to replace the emoji.
            new_text = (
                '<span font="%s %s" fallback="%s">'
                %(self._font, self._fontsize, str(self._fallback).lower())
                + html.escape(emoji)
                + '</span>')
            label.set_text(new_text)
            label.set_use_markup(True)
        GLib.timeout_add(500, self._skin_tone_selected_popover_popdown)

    def on_flowbox_event_box_long_press_begin(self, gesture, event_sequence):
        '''
        Signal handler called when the gesture is recognized

        :param gesture: The object which received the signal
        :type gesture: Gtk.GestureLongPress object
        :param event_sequence: the event sequence that the event belongs to
        :type event_sequence: Gdk.EventSequence structure
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_long_press_begin() %s %s\n'
                %(repr(gesture), repr(event_sequence)))

    def on_flowbox_event_box_long_press_cancel(self, gesture, event_sequence):
        '''
        Signal handler called whenever a sequence is cancelled

        :param gesture: The object which received the signal
        :type gesture: Gtk.GestureLongPress object
        :param event_sequence: the event sequence that the event belongs to
        :type event_sequence: Gdk.EventSequence structure
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_long_press_cancel() %s %s\n'
                %(repr(gesture), repr(event_sequence)))

    def on_flowbox_event_box_long_press_cancelled(self, gesture):
        '''
        Signal handler called whenever a press moved too far, or was
        released before “pressed” happened.

        :param gesture: The object which received the signal
        :type gesture: Gtk.GestureLongPress object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_long_press_cancelled() %s\n'
                %repr(gesture))

    def on_flowbox_event_box_long_press_pressed(
            self, gesture, x, y, event_box):
        '''
        :param gesture: The object which received the signal
        :type gesture: Gtk.GestureLongPress object
        :param x: the X coordinate where the press happened,
                  relative to the widget allocation
        :type x: Integer
        :param y: the Y coordinate where the press happened,
                  relative to the widget allocation
        :type y: Integer
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_long_press_pressed() %s %s %s %s\n'
                %(repr(gesture), x, y, repr(event_box)))
        self._show_skin_tone_popover(event_box)

    def on_flowbox_event_box_button_release(
            self, event_box, event_button):
        '''
        Signal handler for button release events on labels in the flowbox

        :param event_box: The event box containing the label with the emoji.
        :type event_box: Gtk.EventBox object
        :param event_button: The event button
        :type event_button: Gdk.EventButton object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_button_release() '
                + 'event_button.type=%s ' %event_button.type
                + 'event_button.window=%s ' %event_button.window
                + 'event_button.button=%s\n' %event_button.button)
        if event_button.button == 1:
            # Call self._emoji_event_box_selected() in the release
            # event because here we know that it has not been a long
            # press, i.e. no request for a skin tone popover.
            self._emoji_event_box_selected(event_box)
        if event_button.button == 2 and self._skin_tone_popover:
            # not used if the popover is modal, in that case this
            # handler for the button release event will not be called.
            if GTK_VERSION >= (3, 22, 0):
                self._skin_tone_popover.popdown()
            self._skin_tone_popover.hide()
        if event_button.button == 3 and self._emoji_info_popover:
            # not used if the popover is modal, in that case this
            # handler for the button release event will not be called.
            if GTK_VERSION >= (3, 22, 0):
                self._emoji_info_popover.popdown()
            self._emoji_info_popover.hide()
        return Gdk.EVENT_PROPAGATE

    def _show_skin_tone_popover(self, event_box):
        '''
        Show a skin tone popover if there is an emoji in this event box
        which supports skin tones.

        If there is no emoji or it does not support skin tones, do nothing.

        :param event_box: The event box containing the label with the emoji.
                          The popover will be relative to this event box.
        :type event_box: Gtk.EventBox object
        '''
        text = event_box.get_child().get_label()
        (emoji, name) = self._parse_emoji_and_name_from_text(text)
        if not emoji:
            return
        skin_tone_variants = []
        for skin_tone_variant in self._emoji_matcher.skin_tone_variants(emoji):
            skin_tone_variants.append(
                self._variation_selector_normalize_for_font(skin_tone_variant))
        if len(skin_tone_variants) <= 1:
            return
        self._skin_tone_popover = Gtk.Popover()
        self._skin_tone_popover.set_modal(True)
        # Gtk.PopoverConstraint.NONE has an effect only under
        # Wayland, under X11 popovers are always constrained to
        # the toplevel window
        # Gtk.PopoverConstraint.NONE behaves a bit weird under
        # Wayland though, the popover can be outside of the
        # root window of the desktop. Better constrain it to
        # the toplevel window under Wayland as well.
        self._skin_tone_popover.set_constrain_to(
            Gtk.PopoverConstraint.WINDOW)
        self._skin_tone_popover.set_relative_to(event_box)
        self._skin_tone_popover.set_position(Gtk.PositionType.TOP)
        self._skin_tone_popover.set_vexpand(False)
        self._skin_tone_popover.set_hexpand(False)
        if name:
            rectangle = Gdk.Rectangle()
            rectangle.x = 0
            rectangle.y = 0
            rectangle.width = self._fontsize * 1.5
            rectangle.height = self._fontsize * 1.5
            self._skin_tone_popover.set_pointing_to(rectangle)
        skin_tone_popover_grid = Gtk.Grid()
        margin = 1
        skin_tone_popover_grid.set_margin_start(margin)
        skin_tone_popover_grid.set_margin_end(margin)
        skin_tone_popover_grid.set_margin_top(margin)
        skin_tone_popover_grid.set_margin_bottom(margin)
        skin_tone_popover_flowbox = Gtk.FlowBox()
        skin_tone_popover_flowbox.get_style_context().add_class('view')
        skin_tone_popover_flowbox.set_valign(Gtk.Align.START)
        skin_tone_popover_flowbox.set_min_children_per_line(3)
        skin_tone_popover_flowbox.set_max_children_per_line(3)
        skin_tone_popover_flowbox.set_row_spacing(0)
        skin_tone_popover_flowbox.set_column_spacing(0)
        skin_tone_popover_flowbox.set_activate_on_single_click(True)
        skin_tone_popover_flowbox.set_selection_mode(
            Gtk.SelectionMode.NONE)
        skin_tone_popover_flowbox.set_can_focus(False)
        skin_tone_popover_flowbox.set_homogeneous(False)
        skin_tone_popover_flowbox.set_hexpand(False)
        skin_tone_popover_flowbox.set_vexpand(False)
        skin_tone_popover_flowbox.connect(
            'child-activated', self.on_skin_tone_selected)
        for skin_tone_variant in skin_tone_variants:
            label = Gtk.Label()
            label.set_text(
                '<span font="%s %s" fallback="%s">'
                %(self._font, self._fontsize, str(self._fallback).lower())
                + html.escape(skin_tone_variant)
                + '</span>')
            label.set_use_markup(True)
            label.set_can_focus(False)
            label.set_selectable(False)
            label.set_hexpand(False)
            label.set_vexpand(False)
            label.set_xalign(0.5)
            label.set_yalign(0.5)
            # Gtk.Align.FILL, Gtk.Align.START, Gtk.Align.END,
            # Gtk.Align.CENTER, Gtk.Align.BASELINE
            label.set_halign(Gtk.Align.FILL)
            label.set_valign(Gtk.Align.FILL)
            margin = 0
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            label.set_tooltip_text(_('Left click to copy'))
            skin_tone_popover_flowbox.insert(label, -1)
        for child in skin_tone_popover_flowbox.get_children():
            child.set_can_focus(False)
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_capture_button_press(False)
        scrolled_window.set_kinetic_scrolling(False)
        scrolled_window.set_overlay_scrolling(True)
        scrolled_window.add(skin_tone_popover_flowbox)
        skin_tone_popover_grid.add(scrolled_window)
        self._skin_tone_popover.add(skin_tone_popover_grid)
        skin_tone_popover_grid.show_all()
        (dummy_minimum_width_flowbox, natural_width_flowbox) = (
            skin_tone_popover_flowbox.get_preferred_width())
        (dummy_minimim_height_flowbox, natural_height_flowbox) = (
            skin_tone_popover_flowbox.get_preferred_height())
        (window_width, window_height) = self.get_size()
        scrolled_window.set_size_request(
            min(0.6 * window_width, natural_width_flowbox),
            min(0.6 * window_height, natural_height_flowbox))
        if GTK_VERSION >= (3, 22, 0):
            self._skin_tone_popover.popup()
        self._skin_tone_popover.show_all()

    def _show_emoji_info_popover(self, event_box):
        '''
        Show an info popover if there is an emoji in this event box.

        If there is no emoji in the event box, do nothing.

        :param event_box: The event box containing the label with the emoji.
                          The popover will be relative to this event box.
        :type event_box: Gtk.EventBox object
        '''
        text = event_box.get_child().get_label()
        (emoji, name) = self._parse_emoji_and_name_from_text(text)
        if not emoji:
            return
        self._emoji_info_popover = Gtk.Popover()
        self._emoji_info_popover.set_modal(True)
        # Gtk.PopoverConstraint.NONE has an effect only under
        # Wayland, under X11 popovers are always constrained to
        # the toplevel window
        # Gtk.PopoverConstraint.NONE behaves a bit weird under
        # Wayland though, the popover can be outside of the
        # root window of the desktop. Better constrain it to
        # the toplevel window under Wayland as well.
        self._emoji_info_popover.set_constrain_to(
            Gtk.PopoverConstraint.WINDOW)
        self._emoji_info_popover.set_relative_to(event_box)
        self._emoji_info_popover.set_position(Gtk.PositionType.RIGHT)
        self._emoji_info_popover.set_vexpand(False)
        self._emoji_info_popover.set_hexpand(False)
        if name:
            rectangle = Gdk.Rectangle()
            rectangle.x = 0
            rectangle.y = 0
            rectangle.width = self._fontsize * 1.5
            rectangle.height = self._fontsize * 1.5
            self._emoji_info_popover.set_pointing_to(rectangle)
        emoji_info_popover_vbox = Gtk.VBox()
        emoji_info_popover_vbox.set_vexpand(False)
        emoji_info_popover_vbox.set_hexpand(False)
        margin = 0
        emoji_info_popover_vbox.set_margin_start(margin)
        emoji_info_popover_vbox.set_margin_end(margin)
        emoji_info_popover_vbox.set_margin_top(margin)
        emoji_info_popover_vbox.set_margin_bottom(margin)
        emoji_info_popover_vbox.set_spacing(margin)
        emoji_info_popover_scroll = Gtk.ScrolledWindow()
        emoji_info_popover_vbox.pack_start(
            emoji_info_popover_scroll, True, True, 0)
        emoji_info_popover_listbox = Gtk.ListBox()
        emoji_info_popover_listbox.set_visible(True)
        emoji_info_popover_listbox.set_can_focus(False)
        emoji_info_popover_listbox.set_vexpand(False)
        emoji_info_popover_listbox.set_hexpand(False)
        emoji_info_popover_listbox.set_selection_mode(
            Gtk.SelectionMode.NONE)
        emoji_info_popover_listbox.set_activate_on_single_click(True)
        emoji_info_popover_scroll.add(emoji_info_popover_listbox)
        label = Gtk.Label()
        label.set_hexpand(False)
        label.set_vexpand(False)
        label.set_halign(Gtk.Align.START)
        label.set_markup(
            '<span font="%s %s" fallback="%s">'
            %(self._font, self._fontsize * 3, str(self._fallback).lower())
            + html.escape(emoji)
            + '</span>')
        emoji_info_popover_listbox.insert(label, -1)
        for description in self._emoji_descriptions(emoji):
            label_description = Gtk.Label()
            margin = 0
            label_description.set_margin_start(margin)
            label_description.set_margin_end(margin)
            label_description.set_margin_top(margin)
            label_description.set_margin_bottom(margin)
            label_description.set_selectable(True)
            label_description.set_hexpand(False)
            label_description.set_vexpand(False)
            label_description.set_halign(Gtk.Align.START)
            label_description.set_line_wrap(True)
            label_description.set_markup(description)
            emoji_info_popover_listbox.insert(label_description, -1)
        if (self._emoji_matcher.cldr_order(emoji) < 0xFFFFFFFF
                or self._emoji_matcher.properties(emoji)):
            linkbutton = Gtk.LinkButton.new_with_label(
                _('Lookup on emojipedia'))
            linkbutton.set_uri(
                'http://emojipedia.org/emoji/' + emoji + '/')
            linkbutton.set_halign(Gtk.Align.START)
            emoji_info_popover_listbox.insert(linkbutton, -1)
        for row in emoji_info_popover_listbox.get_children():
            row.set_activatable(False)
            row.set_selectable(False)
            row.set_can_focus(False)
        self._emoji_info_popover.add(emoji_info_popover_vbox)
        emoji_info_popover_vbox.show_all()
        (dummy_minimum_width_vbox, natural_width_vbox) = (
            emoji_info_popover_vbox.get_preferred_width())
        (dummy_minimum_height_vbox, natural_height_vbox) = (
            emoji_info_popover_vbox.get_preferred_height())
        (dummy_minimum_width_listbox, natural_width_listbox) = (
            emoji_info_popover_listbox.get_preferred_width())
        (dummy_minimim_height_listbox, natural_height_listbox) = (
            emoji_info_popover_listbox.get_preferred_height())
        (window_width, window_height) = self.get_size()
        self._emoji_info_popover.set_size_request(
            min(0.6 * window_width,
                natural_width_vbox + natural_width_listbox),
            min(0.6 * window_height,
                natural_height_vbox + natural_height_listbox))
        if GTK_VERSION >= (3, 22, 0):
            self._emoji_info_popover.popup()
        self._emoji_info_popover.show_all()

    def on_flowbox_event_box_button_press(self, event_box, event_button):
        '''Signal handler for button presses in flowbox children

        Returns Gdk.EVENT_STOP (True) to prevent a long press gesture
        from being cancelled.  (see:
        https://developer.gnome.org/gdk3/stable/gdk3-Events.html) This
        prevents the handler for the flowbox selection to be called
        though, i.e. on_emoji_selected() is not called. Therefore, the
        emoji selection needs to be handled in the release event
        handler which is only called when it was not a long press.

        :param event_box:
        :type event_box: GtkEventBox object
        :param event_button:
        :type event_button: Gdk.EventButton object
        :rtype: Boolean

        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_flowbox_event_box_button_press() '
                + 'event_button.type=%s ' %event_button.type
                + 'event_button.window=%s ' %event_button.window
                + 'event_button.button=%s\n' %event_button.button)
        if event_button.type != Gdk.EventType.BUTTON_PRESS:
            # ignore double and triple clicks i.e. ignore
            # Gdk.EventType.2BUTTON_PRESS and
            # Gdk.EventType.3BUTTON_PRESS.
            # https://developer.gnome.org/gdk3/stable/gdk3-Event-Structures.html#GdkEventButton
            return Gdk.EVENT_STOP
        # Button 1 could turn into long press requesting a skin tone
        # popover which is handled in
        # on_flowbox_event_box_long_press_pressed(). Therefore, do not
        # handle it here. Handle it in the release event instead because
        # then we know that it has not been a long press.
        if event_button.button == 2:
            self._show_skin_tone_popover(event_box)
            return Gdk.EVENT_STOP
        if event_button.button == 3:
            self._show_emoji_info_popover(event_box)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_STOP

    def on_fontsize_adjustment_value_changed(self, adjustment):
        '''
        The fontsize adjustment in the header bar has been changed

        :param adjustment: The adjustment used to change the fontsize
        :type adjustment: Gtk.Adjustment object
        '''
        value = adjustment.get_value()
        if _ARGS.debug:
            sys.stdout.write(
                'on_fontsize_adjustment_value_changed() value = %s\n'
                %value)
        self._fontsize = value
        self._save_options()
        self._busy_start()
        GLib.idle_add(self._change_flowbox_font)

    def on_fallback_check_button_toggled(self, check_button):
        '''
        The fallback check button in the header bar has been toggled

        :param toggle_button: The check button used to select whether
                              fallback fonts should be used.
        :type adjustment: Gtk.CheckButton object
        '''
        self._fallback = check_button.get_active()
        if _ARGS.debug:
            sys.stdout.write(
                'on_fallback_check_button_toggled() self._fallback = %s\n'
                %self._fallback)
        self._save_options()
        self._busy_start()
        GLib.idle_add(self._change_flowbox_font)

    def _list_font_names(self):
        '''
        Returns a list of font names available on the system

        :rtype: List of strings
        '''
        good_emoji_fonts = [
            'Noto Color Emoji 🎨',
            'Twemoji 🎨', # color
            'Apple Color Emoji 🎨', # color
            'Emoji Two 🎨', # color
            'Emoji One 🎨', # color
            'JoyPixels 🎨', # color
            'Symbola 🙾', # black and white
            'Noto Emoji 🙾', # black and white
            'Android Emoji 🙾', # black and white
            'Segoe UI Emoji 🙾', # seems to be black and white
            'Twitter Color Emoji 🙾', # seems to be black and white
        ]
        available_good_emoji_fonts = [
            'emoji (' + _('System default') + ')',
            'text (' + _('System default') + ')',
            'unqualified (' + _('System default') + ')',
        ]
        available_good_emoji_fonts.append('')
        pango_context = self.get_pango_context()
        families = pango_context.list_families()
        names = sorted([family.get_name() for family in families])
        for font in good_emoji_fonts:
            name = font.split(' ')[0]
            if name in names:
                names.remove(name)
                available_good_emoji_fonts.append(font)
        available_good_emoji_fonts.append('')
        names = available_good_emoji_fonts + names
        return names

    def _fill_listbox_font(self, filter_text):
        '''
        Fill the listbox of fonts to choose from

        :param filter_text: The filter text to limit the
                            fonts listed. Only fonts which
                            contain the the filter text as
                            a substring (ignoring case and spaces)
                            are listed.
        :type filter_text: String
        '''
        if _ARGS.debug:
            sys.stdout.write(
                '_fill_listbox_font() filter_text = %s\n'
                %filter_text)
        for child in self._font_popover_scroll.get_children():
            self._font_popover_scroll.remove(child)
        self._font_popover_listbox = Gtk.ListBox()
        self._font_popover_scroll.add(self._font_popover_listbox)
        self._font_popover_listbox.set_visible(True)
        self._font_popover_listbox.set_vexpand(True)
        self._font_popover_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._font_popover_listbox.set_activate_on_single_click(True)
        self._font_popover_listbox.connect(
            'row-selected', self.on_font_selected)
        fonts = [
            font
            for font in self._list_font_names()
            if filter_text.replace(' ', '').lower()
            in font.replace(' ', '').lower()]
        for font in fonts:
            label = Gtk.Label()
            label.set_text(font)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._font_popover_listbox.insert(label, -1)
        for row in self._font_popover_listbox.get_children():
            row.get_style_context().add_class('font')
        self._font_popover.show_all()

    def on_font_search_entry_search_changed(self, search_entry):
        '''
        Signal handler for changed text in the font search entry

        :param widget: The search entry
        :type widget: Gtk.SearchEntry object
        '''
        filter_text = search_entry.get_text()
        if _ARGS.debug:
            sys.stdout.write(
                'on_font_search_entry_search_changed() filter_text = %s\n'
                %filter_text)
        self._fill_listbox_font(filter_text)

    def on_font_selected(self, _listbox, listbox_row):
        '''
        Signal handler for selecting a font

        :param _listbox: The list box used to select a font
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing a font name
        :type listbox_row: Gtk.ListBoxRow object
        '''
        font = listbox_row.get_child().get_text().split(' ')[0]
        if _ARGS.debug:
            sys.stdout.write(
                'on_font_selected() font = %s\n' %repr(font))
        if font == '':
            font = 'emoji'
        if font != self._font and (
                font == 'emoji' or font == 'text' or font == 'unqualified'):
            self._fallback = True
            self._fallback_check_button.set_active(True)
        else:
            self._fallback = False
            self._fallback_check_button.set_active(False)
        if GTK_VERSION >= (3, 22, 0):
            self._font_popover.popdown()
        self._font_popover.hide()
        self._font = font
        self._font_button.set_label(self._font)
        self._save_options()
        self._busy_start()
        GLib.idle_add(self._change_flowbox_font)

    def on_font_button_clicked(self, _button):
        '''
        The font button in the header bar has been clicked

        :param _button: The font button
        :type _button: Gtk.Button object
        '''
        if _ARGS.debug:
            sys.stdout.write(
                'on_font_button_clicked()\n')
        self._font_popover = Gtk.Popover()
        self._font_popover.set_relative_to(self._font_button)
        self._font_popover.set_position(Gtk.PositionType.BOTTOM)
        self._font_popover.set_vexpand(True)
        font_popover_vbox = Gtk.VBox()
        margin = 12
        font_popover_vbox.set_margin_start(margin)
        font_popover_vbox.set_margin_end(margin)
        font_popover_vbox.set_margin_top(margin)
        font_popover_vbox.set_margin_bottom(margin)
        font_popover_vbox.set_spacing(margin)
        font_popover_label = Gtk.Label()
        font_popover_label.set_text(_('Set Font'))
        font_popover_label.set_visible(True)
        font_popover_label.set_halign(Gtk.Align.FILL)
        font_popover_vbox.pack_start(
            font_popover_label, False, False, 0)
        font_popover_search_entry = Gtk.SearchEntry()
        font_popover_search_entry.set_can_focus(True)
        font_popover_search_entry.set_visible(True)
        font_popover_search_entry.set_halign(Gtk.Align.FILL)
        font_popover_search_entry.set_hexpand(False)
        font_popover_search_entry.set_vexpand(False)
        font_popover_search_entry.connect(
            'search_changed', self.on_font_search_entry_search_changed)
        font_popover_vbox.pack_start(
            font_popover_search_entry, False, False, 0)
        self._font_popover_scroll = Gtk.ScrolledWindow()
        self._fill_listbox_font('')
        font_popover_vbox.pack_start(
            self._font_popover_scroll, True, True, 0)
        self._font_popover.add(font_popover_vbox)
        if GTK_VERSION >= (3, 22, 0):
            self._font_popover.popup()
        self._font_popover.show_all()

def get_languages():
    '''
    Return the list of languages.

    Get it from the command line option if that is used.
    If not, get it from the environment variables.
    '''
    if _ARGS.languages:
        return _ARGS.languages.split(':')
    environment_variable = os.getenv('LANGUAGE')
    if not environment_variable:
        environment_variable = os.getenv('LC_ALL')
    if not environment_variable:
        environment_variable = os.getenv('LC_MESSAGES')
    if not environment_variable:
        environment_variable = os.getenv('LANG')
    if not environment_variable:
        return ['en_US']
    languages = []
    for language in environment_variable.split(':'):
        languages.append(re.sub(r'[.@].*', '', language))
    return languages

if __name__ == '__main__':
    if _ARGS.debug:
        sys.stdout.write('--- %s ---\n' %time.strftime('%Y-%m-%d: %H:%M:%S'))
        import cProfile
        import pstats
        PROFILE = cProfile.Profile()
        PROFILE.enable()

    # Workaround for
    # https://bugzilla.gnome.org/show_bug.cgi?id=622084
    # Bug 622084 - Ctrl+C does not exit gtk app
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        sys.stderr.write("IBUS-WARNING **: Using the fallback 'C' locale")
        locale.setlocale(locale.LC_ALL, 'C')

    LOCALEDIR = os.getenv("IBUS_LOCALEDIR")
    gettext.bindtextdomain(DOMAINNAME, LOCALEDIR)
    gettext.bind_textdomain_codeset(DOMAINNAME, "UTF-8")

    if _ARGS.version:
        print(version.get_version())
        sys.exit(0)

    EMOJI_PICKER_UI = EmojiPickerUI(
        languages=get_languages(),
        font=_ARGS.font,
        fontsize=_ARGS.fontsize,
        fallback=_ARGS.fallback,
        modal=_ARGS.modal,
        unicode_data_all=_ARGS.all,
        emoji_unicode_min=_ARGS.emoji_unicode_min,
        emoji_unicode_max=_ARGS.emoji_unicode_max)
    Gtk.main()
