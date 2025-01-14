# -*- coding: utf-8 -*-
# vim:et sts=4 sw=4
#
# ibus-typing-booster - A completion input method for IBus
#
# Copyright (c) 2012-2013 Anish Patil <apatil@redhat.com>
# Copyright (c) 2012-2018 Mike FABIAN <mfabian@redhat.com>
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
The setup tool for ibus typing booster.
'''

import sys
import os
import re
import html
import signal
import argparse
import locale
from time import strftime
import dbus
import dbus.service

from gi import require_version
require_version('Gio', '2.0')
from gi.repository import Gio
require_version('GLib', '2.0')
from gi.repository import GLib

# set_prgname before importing other modules to show the name in warning
# messages when import modules are failed. E.g. Gtk.
GLib.set_application_name('Typing Booster Preferences')
# This makes gnome-shell load the .desktop file when running under Wayland:
GLib.set_prgname('ibus-setup-typing-booster')

require_version('Gdk', '3.0')
from gi.repository import Gdk
require_version('Gtk', '3.0')
from gi.repository import Gtk
require_version('Pango', '1.0')
from gi.repository import Pango
require_version('IBus', '1.0')
from gi.repository import IBus
from pkginstall import InstallPkg
from i18n import DOMAINNAME, _, init as i18n_init

IMPORT_LANGTABLE_SUCCESSFUL = False
try:
    import langtable
    IMPORT_LANGTABLE_SUCCESSFUL = True
except (ImportError,):
    IMPORT_LANGTABLE_SUCCESSFUL = False

sys.path = [sys.path[0]+'/../engine'] + sys.path
from m17n_translit import Transliterator
import tabsqlitedb
import itb_util
import itb_emoji

GTK_VERSION = (Gtk.get_major_version(),
               Gtk.get_minor_version(),
               Gtk.get_micro_version())

def parse_args():
    '''
    Parse the command line arguments.
    '''
    parser = argparse.ArgumentParser(
        description='ibus-typing-booster setup tool')
    parser.add_argument(
        '-q', '--no-debug',
        action='store_true',
        default=False,
        help=('Do not redirect stdout and stderr to '
              + '~/.local/share/ibus-typing-booster/setup-debug.log, '
              + 'default: %(default)s'))
    return parser.parse_args()

_ARGS = parse_args()

class SetupUI(Gtk.Window):
    '''
    User interface of the setup tool
    '''
    def __init__(self):
        Gtk.Window.__init__(self, title='🚀 ' + _('Preferences'))
        self.set_name('TypingBoosterPreferences')
        self.set_modal(True)
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(
            b'''
            #TypingBoosterPreferences {
            }
            row { /* This is for listbox rows */
                border-style: groove;
                border-width: 0.05px;
            }
            ''')
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.tabsqlitedb = tabsqlitedb.TabSqliteDb()

        self._gsettings = Gio.Settings(
            schema='org.freedesktop.ibus.engine.typing-booster')
        self._gsettings.connect('changed', self.on_gsettings_value_changed)
        self.set_title('🚀 ' + _('Preferences for ibus-typing-booster'))
        # https://tronche.com/gui/x/icccm/sec-4.html#WM_CLASS
        # gnome-shell seems to use the first argument of set_wmclass()
        # to find the .desktop file. If the .desktop file can be
        # found, the name shown by gnome-shell in the top bar comes
        # from that .desktop file and the icon to show is also read
        # from that .desktop file. If the .desktop file cannot be
        # found, the second argument of set_wmclass() is shown by
        # gnome-shell in the top bar.
        #
        # It only works like this when gnome-shell runs under Xorg
        # though, under Wayland things are different.
        self.set_wmclass(
            'ibus-setup-typing-booster', 'Typing Booster Preferences')

        self.connect('destroy-event', self.on_destroy_event)
        self.connect('delete-event', self.on_delete_event)

        self._main_container = Gtk.VBox()
        self.add(self._main_container)
        self._notebook = Gtk.Notebook()
        self._notebook.set_visible(True)
        self._notebook.set_can_focus(False)
        self._notebook.set_scrollable(True)
        self._notebook.set_hexpand(True)
        self._notebook.set_vexpand(True)
        self._main_container.pack_start(self._notebook, True, True, 0)
        self._dialog_action_area = Gtk.ButtonBox()
        self._dialog_action_area.set_visible(True)
        self._dialog_action_area.set_can_focus(False)
        self._dialog_action_area.set_hexpand(True)
        self._dialog_action_area.set_vexpand(False)
        self._dialog_action_area.set_layout(Gtk.ButtonBoxStyle.EDGE)
        self._main_container.pack_end(self._dialog_action_area, True, True, 0)
        self._about_button = Gtk.Button(label=_('About'))
        self._about_button.connect('clicked', self.on_about_button_clicked)
        self._dialog_action_area.add(self._about_button)
        self._close_button = Gtk.Button()
        self._close_button_label = Gtk.Label()
        self._close_button_label.set_text_with_mnemonic(_('_Close'))
        self._close_button.add(self._close_button_label)
        self._close_button.connect('clicked', self.on_close_clicked)
        self._dialog_action_area.add(self._close_button)

        grid_border_width = 10
        grid_row_spacing = 10
        grid_column_spacing = 10

        self._dictionaries_and_input_methods_vbox = Gtk.VBox()
        margin = 10
        self._dictionaries_and_input_methods_vbox.set_margin_start(margin)
        self._dictionaries_and_input_methods_vbox.set_margin_end(margin)
        self._dictionaries_and_input_methods_vbox.set_margin_top(margin)
        self._dictionaries_and_input_methods_vbox.set_margin_bottom(margin)
        self._dictionaries_and_input_methods_label = Gtk.Label()
        self._dictionaries_and_input_methods_label.set_text(
            # Translators: This is the label of a tab in the setup
            # tool. Here the user can setup the dictionaries for the
            # languages he wants to use and the input methods to use
            # to be able to type all the languages he is interested
            # in.
            _('Dictionaries and input methods'))

        self._options_grid = Gtk.Grid()
        self._options_grid.set_visible(True)
        self._options_grid.set_can_focus(False)
        self._options_grid.set_border_width(grid_border_width)
        self._options_grid.set_row_spacing(grid_row_spacing)
        self._options_grid.set_column_spacing(grid_column_spacing)
        self._options_grid.set_row_homogeneous(False)
        self._options_grid.set_column_homogeneous(True)
        self._options_grid.set_hexpand(True)
        self._options_grid.set_vexpand(False)
        self._options_label = Gtk.Label()
        # Translators: This is the label of a tab in the setup tool.
        # Here the user can set up some options which influence the
        # behaviour of ibus-typing-booster.
        self._options_label.set_text(_('Options'))

        self._custom_shortcuts_grid = Gtk.Grid()
        self._custom_shortcuts_grid.set_visible(True)
        self._custom_shortcuts_grid.set_can_focus(False)
        self._custom_shortcuts_grid.set_border_width(grid_border_width)
        self._custom_shortcuts_grid.set_row_spacing(grid_row_spacing)
        self._custom_shortcuts_grid.set_column_spacing(grid_column_spacing)
        self._custom_shortcuts_grid.set_row_homogeneous(False)
        self._custom_shortcuts_grid.set_column_homogeneous(True)
        self._custom_shortcuts_label = Gtk.Label()
        # Translators: This is a label of a tab in the setup tool.
        # Here the user can create custom shortcuts. For example if
        # the user wants that whenever he types “rotfl” that “rolling
        # on the floor laughing” is shown as a high priority
        # candidate, he can define such a custom shortcut here.
        self._custom_shortcuts_label.set_text(_('Custom shortcuts'))

        self._keybindings_vbox = Gtk.VBox()
        margin = 10
        self._keybindings_vbox.set_margin_start(margin)
        self._keybindings_vbox.set_margin_end(margin)
        self._keybindings_vbox.set_margin_top(margin)
        self._keybindings_vbox.set_margin_bottom(margin)
        self._keybindings_label = Gtk.Label()
        # Translators: This is the label of a tab in the setup tool.
        # Here the user can customize the key bindings to execute
        # certain commands of ibus-typing-booster. For example
        # which key to use to request completion, which key to
        # use to move to the next completion candidate etc...
        self._keybindings_label.set_text(_('Key bindings'))

        self._appearance_grid = Gtk.Grid()
        self._appearance_grid.set_visible(True)
        self._appearance_grid.set_can_focus(False)
        self._appearance_grid.set_border_width(grid_border_width)
        self._appearance_grid.set_row_spacing(grid_row_spacing)
        self._appearance_grid.set_column_spacing(grid_column_spacing)
        self._appearance_grid.set_row_homogeneous(False)
        self._appearance_grid.set_column_homogeneous(True)
        self._appearance_grid.set_hexpand(True)
        self._appearance_grid.set_vexpand(False)
        self._appearance_label = Gtk.Label()
        # Translators: This is the label of a tab in the setup tool.
        # Here the user can set up some options which influence how
        # ibus-typing-booster looks like, i.e. something like whether
        # extra info should be shown on top of the candidate list and
        # how many entries one page of the candidate list should have.
        # Also one can choose here which colours to use for different
        # types of candidates (candidates from the user database, from
        # dictionaries, or from spellchecking) and/or whether
        # diffent types of candidates should be marked with labels.
        self._appearance_label.set_text(_('Appearance'))

        self._speech_recognition_grid = Gtk.Grid()
        self._speech_recognition_grid.set_visible(True)
        self._speech_recognition_grid.set_can_focus(False)
        self._speech_recognition_grid.set_border_width(grid_border_width)
        self._speech_recognition_grid.set_row_spacing(grid_row_spacing)
        self._speech_recognition_grid.set_column_spacing(grid_column_spacing)
        self._speech_recognition_grid.set_row_homogeneous(False)
        self._speech_recognition_grid.set_column_homogeneous(False)
        self._speech_recognition_grid.set_hexpand(True)
        self._speech_recognition_grid.set_vexpand(False)
        self._speech_recognition_label = Gtk.Label()
        # Translators: This is the label of a tab in the setup tool.
        # Here the user can set up some options related to speech
        # recognition.
        self._speech_recognition_label.set_text(_('Speech recognition'))

        self._notebook.append_page(
            self._dictionaries_and_input_methods_vbox,
            self._dictionaries_and_input_methods_label)
        self._notebook.append_page(
            self._options_grid,
            self._options_label)
        self._notebook.append_page(
            self._custom_shortcuts_grid,
            self._custom_shortcuts_label)
        self._notebook.append_page(
            self._keybindings_vbox,
            self._keybindings_label)
        self._notebook.append_page(
            self._appearance_grid,
            self._appearance_label)
        self._notebook.append_page(
            self._speech_recognition_grid,
            self._speech_recognition_label)

        self._keybindings = {}
        # Don’t just use get_value(), if the user has changed the
        # settings, get_value() will get the user settings and new
        # keybindings might have been added by an update to the default
        # settings. Therefore, get the default settings first and
        # update them with the user settings:
        self._keybindings = itb_util.variant_to_value(
            self._gsettings.get_default_value('keybindings'))
        itb_util.dict_update_existing_keys(
            self._keybindings,
            itb_util.variant_to_value(
                self._gsettings.get_value('keybindings')))

        self._tab_enable_checkbutton = Gtk.CheckButton(
            # Translators: If this option is on, suggestions are not
            # shown by default. Typing a key is then necessary to show
            # the list of suggestions. The key to use for this can be
            # changed in the key bindings settings. By default it is
            # the Tab key. After a commit the suggestions are hidden
            # again until the next key bound to this command is typed.
            label=_('Enable suggestions by key (Default is the Tab key)'))
        self._tab_enable_checkbutton.set_tooltip_text(
            _('If this option is on, suggestions are not '
              + 'shown by default. Typing a key is then '
              + 'necessary to show the list of suggestions. '
              + 'The key to use for this can be changed in '
              + 'the key bindings settings. By default it is '
              + 'the Tab key. After a commit the suggestions '
              + 'are hidden again until the next key bound to '
              + 'this command is typed.'))
        self._tab_enable_checkbutton.connect(
            'clicked', self.on_tab_enable_checkbutton)
        self._options_grid.attach(
            self._tab_enable_checkbutton, 0, 0, 2, 1)
        self._tab_enable = itb_util.variant_to_value(
            self._gsettings.get_value('tabenable'))
        if self._tab_enable is None:
            self._tab_enable = False
        if  self._tab_enable is True:
            self._tab_enable_checkbutton.set_active(True)

        self._inline_completion_checkbutton = Gtk.CheckButton(
            # Translators: Whether the best completion is first shown
            # inline in the preedit instead of showing a full
            # candidate list. The inline candidate can be selected by
            # typing Tab and then committed as usual, for example by
            # typing Space or Control+Space. Typing Tab again moves to
            # the next candidate and opens the full candidate list.
            label=_('Use inline completion'))
        self._inline_completion_checkbutton.set_tooltip_text(
            _('Whether the best completion is first shown inline '
              + 'in the preedit instead of showing a full candidate '
              + 'list. The inline candidate can be selected by typing '
              + 'Tab and then committed as usual, for example by '
              + 'typing Space or Control+Space. Typing Tab again '
              + 'moves to the next candidate and opens the full '
              + 'candidate list.'))
        self._inline_completion_checkbutton.connect(
            'clicked', self.on_inline_completion_checkbutton)
        self._options_grid.attach(
            self._inline_completion_checkbutton, 0, 1, 2, 1)
        self._inline_completion = itb_util.variant_to_value(
            self._gsettings.get_value('inlinecompletion'))
        if self._inline_completion is None:
            self._inline_completion = False
        if  self._inline_completion is True:
            self._inline_completion_checkbutton.set_active(True)

        self._auto_select_candidate_checkbutton = Gtk.CheckButton(
            # Translators: What you type will automatically be
            # corrected to the best candidate by selecting the best
            # candidate automatically. If this option is off you have
            # to select a candidate manually by using the key binding
            # to select the next candidate. If this option is on and
            # you do not want to use the automatically selected
            # candidate, you can use the key binding for the “cancel”
            # command which will deselect all candidates.
            label=_('Automatically select the best candidate'))
        self._auto_select_candidate_checkbutton.set_tooltip_text(
            _('What you type will automatically be corrected to the best '
              + 'candidate by selecting the best candidate automatically. If '
              + 'this option is off you have to select a candidate manually '
              + 'by using the key binding to select the next candidate. '
              + 'If this option is on and you do not want to use the '
              + 'automatically selected candidate, you can use the key binding '
              + 'for the “cancel” command which will deselect all '
              + 'candidates.'))
        self._auto_select_candidate_checkbutton.connect(
            'clicked', self.on_auto_select_candidate_checkbutton)
        self._options_grid.attach(
            self._auto_select_candidate_checkbutton, 0, 2, 2, 1)
        self._auto_select_candidate = itb_util.variant_to_value(
            self._gsettings.get_value('autoselectcandidate'))
        if self._auto_select_candidate is None:
            self._auto_select_candidate = False
        if self._auto_select_candidate is True:
            self._auto_select_candidate_checkbutton.set_active(True)

        self._add_space_on_commit_checkbutton = Gtk.CheckButton(
            # Translators: Add a space if a candidate from the
            # candidate list is committed by clicking it
            # with the mouse.
            label=_('Add a space when committing by mouse click'))
        self._add_space_on_commit_checkbutton.set_tooltip_text(
            _('Add a space if a candidate from the candidate '
              + 'list is committed by clicking it '
              + 'with the mouse.'))
        self._add_space_on_commit_checkbutton.connect(
            'clicked', self.on_add_space_on_commit_checkbutton)
        self._options_grid.attach(
            self._add_space_on_commit_checkbutton, 0, 3, 2, 1)
        self._add_space_on_commit = itb_util.variant_to_value(
            self._gsettings.get_value('addspaceoncommit'))
        if self._add_space_on_commit is None:
            self._add_space_on_commit = True
        if self._add_space_on_commit is True:
            self._add_space_on_commit_checkbutton.set_active(True)

        self._remember_last_used_preedit_ime_checkbutton = Gtk.CheckButton(
            # Translators: If more then one input method is used at
            # the same time, one of them is used for the preedit.
            # Which input method is used for the preedit can be
            # changed via the menu or via shortcut keys. If this
            # option is enabled, such a change is remembered even if
            # the session is restarted.
            label=_('Remember last used preedit input method'))
        self._remember_last_used_preedit_ime_checkbutton.set_tooltip_text(
            _('If more then one input method is used at the same '
              + 'time, one of them is used for the preedit. '
              + 'Which input method is used for the preedit can '
              + 'be changed via the menu or via shortcut keys. '
              + 'If this option is enabled, such a change is '
              + 'remembered even if the session is restarted.'))
        self._remember_last_used_preedit_ime_checkbutton.connect(
            'clicked', self.on_remember_last_used_preedit_ime_checkbutton)
        self._options_grid.attach(
            self._remember_last_used_preedit_ime_checkbutton, 0, 4, 2, 1)
        self._remember_last_used_preedit_ime = itb_util.variant_to_value(
            self._gsettings.get_value('rememberlastusedpreeditime'))
        if self._remember_last_used_preedit_ime is None:
            self._remember_last_used_preedit_ime = False
        if  self._remember_last_used_preedit_ime is True:
            self._remember_last_used_preedit_ime_checkbutton.set_active(True)

        self._emoji_predictions_checkbutton = Gtk.CheckButton(
            # Translators: Whether Unicode symbols and emoji should be
            # included in the predictions. Emoji are pictographs like
            # ☺♨⛵…. Unicode symbols are other symbols like
            # mathematical symbols (∀∑∯…), arrows (←↑↔…), currency
            # symbols (€₹₺…), braille patterns (⠥⠩…), and many other
            # symbols. These are technically not emoji but
            # nevertheless useful symbols.
            label=_('Unicode symbols and emoji predictions'))
        self._emoji_predictions_checkbutton.set_tooltip_text(
            _('Whether Unicode symbols and emoji should be '
              + 'included in the predictions. Emoji are pictographs '
              + 'like ☺♨⛵…. Unicode symbols are other symbols like '
              + 'mathematical symbols (∀∑∯…), arrows (←↑↔…), currency '
              + 'symbols (€₹₺…), braille patterns (⠥⠩…), and many '
              + 'other symbols. These are technically not emoji but '
              + 'nevertheless useful symbols.'))
        self._emoji_predictions_checkbutton.connect(
            'clicked', self.on_emoji_predictions_checkbutton)
        self._options_grid.attach(
            self._emoji_predictions_checkbutton, 0, 5, 2, 1)
        self._emoji_predictions = itb_util.variant_to_value(
            self._gsettings.get_value('emojipredictions'))
        if self._emoji_predictions is None:
            self._emoji_predictions = False
        if self._emoji_predictions is True:
            self._emoji_predictions_checkbutton.set_active(True)

        self._off_the_record_checkbutton = Gtk.CheckButton(
            # Translators: While “Off the record” mode is on, learning
            # from user input is disabled. If learned user input is
            # available, predictions are usually much better than
            # predictions using only dictionaries. Therefore, one
            # should use this option sparingly. Only if one wants to
            # avoid saving secret user input to disk it might make
            # sense to use this option temporarily.
            label=_('Off the record mode'))
        self._off_the_record_checkbutton.set_tooltip_text(
            _('While “Off the record” mode is on, learning from '
              + 'user input is disabled. If learned user input is '
              + 'available, predictions are usually much better '
              + 'than predictions using only dictionaries. '
              + 'Therefore, one should use this option sparingly. '
              + 'Only if one wants to avoid saving secret user '
              + 'input to disk it might make sense to use this '
              + 'option temporarily.'))
        self._off_the_record_checkbutton.connect(
            'clicked', self.on_off_the_record_checkbutton)
        self._options_grid.attach(
            self._off_the_record_checkbutton, 0, 6, 2, 1)
        self._off_the_record = itb_util.variant_to_value(
            self._gsettings.get_value('offtherecord'))
        if self._off_the_record is None:
            self._off_the_record = False
        if self._off_the_record is True:
            self._off_the_record_checkbutton.set_active(True)

        self._qt_im_module_workaround_checkbutton = Gtk.CheckButton(
            # Translators: Use a workaround for bugs in the input
            # method modules of Qt4 and Qt5. Attention, although this
            # workaround makes it work better when the Qt input
            # modules are used, it causes problems when XIM is
            # used. I.e. the XIM module of Qt4 will not work well when
            # this workaround is enabled and input via XIM into X11
            # programs like xterm will not work well either.
            label=_('Use a workaround for a bug in Qt im module'))
        self._qt_im_module_workaround_checkbutton.set_tooltip_text(
            _('Use a workaround for bugs in the input method '
              + 'modules of Qt4 and Qt5. Attention, although '
              + 'this workaround makes it work better when the '
              + 'Qt input modules are used, it causes problems '
              + 'when XIM is used. I.e. the XIM module of Qt4 '
              + 'will not work well when this workaround is '
              + 'enabled and input via XIM into X11 programs '
              + 'like xterm will not work well either.'))
        self._qt_im_module_workaround_checkbutton.connect(
            'clicked', self.on_qt_im_module_workaround_checkbutton)
        self._options_grid.attach(
            self._qt_im_module_workaround_checkbutton, 0, 7, 2, 1)
        self._qt_im_module_workaround = itb_util.variant_to_value(
            self._gsettings.get_value('qtimmoduleworkaround'))
        if self._qt_im_module_workaround is None:
            self._qt_im_module_workaround = False
        if self._qt_im_module_workaround is True:
            self._qt_im_module_workaround_checkbutton.set_active(True)

        self._arrow_keys_reopen_preedit_checkbutton = Gtk.CheckButton(
            # Translators: Whether it is allowed to reopen a preedit
            # when the cursor reaches a word boundary after moving it
            # with the arrow keys. Enabling this option is useful to
            # correct already committed words. But it is quite buggy
            # at the moment and how well it works depends on
            # repetition speed of the arrow keys and system
            # load. Because it is buggy, this option is off by
            # default.
            label=_('Arrow keys can reopen a preedit'))
        self._arrow_keys_reopen_preedit_checkbutton.set_tooltip_text(
            _('Whether it is allowed to reopen a preedit when '
              + 'the cursor reaches a word boundary after moving '
              + 'it with the arrow keys. Enabling this option is '
              + 'useful to correct already committed words. But it '
              + 'is quite buggy at the moment and how well it '
              + 'works depends on repetition speed of the arrow '
              + 'keys and system load. Because it is buggy, '
              + 'this option is off by default.'))
        self._arrow_keys_reopen_preedit_checkbutton.connect(
            'clicked', self.on_arrow_keys_reopen_preedit_checkbutton)
        self._options_grid.attach(
            self._arrow_keys_reopen_preedit_checkbutton, 0, 8, 2, 1)
        self._arrow_keys_reopen_preedit = itb_util.variant_to_value(
            self._gsettings.get_value('arrowkeysreopenpreedit'))
        if self._arrow_keys_reopen_preedit is None:
            self._arrow_keys_reopen_preedit = False
        if self._arrow_keys_reopen_preedit is True:
            self._arrow_keys_reopen_preedit_checkbutton.set_active(True)

        self._auto_commit_characters_label = Gtk.Label()
        self._auto_commit_characters_label.set_text(
            # Translators: The characters in this list cause the
            # preedit to be committed automatically, followed by a
            # space. For example, if “.” is an auto commit character,
            # this saves you typing a space manually after the end of
            # a sentence. You can freely edit this list, a reasonable
            # value might be “.,;:?!)”. You should not add characters
            # to that list which are needed by your input method, for
            # example if you use Latin-Pre (t-latn-pre) it would be a
            # bad idea to add “.” to that list because it would
            # prevent you from typing “.s” to get “ṡ”. You can also
            # disable this feature completely by making the list empty
            # (which is the default).
            _('Auto commit characters:'))
        self._auto_commit_characters_label.set_tooltip_text(
            _('The characters in this list cause the preedit '
              + 'to be committed automatically, followed by '
              + 'a space.  For example, if “.” is an auto '
              + 'commit character, this saves you typing a '
              + 'space manually after the end of a sentence. '
              + 'You can freely edit this list, a reasonable '
              + 'value might be “.,;:?!)”. You should not add '
              + 'characters to that list which are needed by '
              + 'your input method, for example if you use '
              + 'Latin-Pre (t-latn-pre) it would be a bad idea '
              + 'to add “.” to that list because it would prevent '
              + 'you from typing “.s” to get “ṡ”. You can also '
              + 'disable this feature completely by making the '
              + 'list empty (which is the default).'))
        self._auto_commit_characters_label.set_xalign(0)
        self._options_grid.attach(
            self._auto_commit_characters_label, 0, 9, 1, 1)

        self._auto_commit_characters_entry = Gtk.Entry()
        self._options_grid.attach(
            self._auto_commit_characters_entry, 1, 9, 1, 1)
        self._auto_commit_characters = itb_util.variant_to_value(
            self._gsettings.get_value('autocommitcharacters'))
        if not self._auto_commit_characters:
            self._auto_commit_characters = ''
        self._auto_commit_characters_entry.set_text(
            self._auto_commit_characters)
        self._auto_commit_characters_entry.connect(
            'notify::text', self.on_auto_commit_characters_entry)

        self._min_chars_completion_label = Gtk.Label()
        self._min_chars_completion_label.set_text(
            # Translators: Show no suggestions when less than this
            # number of characters have been typed.
            _('Minimum number of chars for completion:'))
        self._min_chars_completion_label.set_tooltip_text(
            _('Show no suggestions when less than this number '
              + 'of characters have been typed.'))
        self._min_chars_completion_label.set_xalign(0)
        self._options_grid.attach(
            self._min_chars_completion_label, 0, 10, 1, 1)

        self._min_char_complete_adjustment = Gtk.SpinButton()
        self._min_char_complete_adjustment.set_visible(True)
        self._min_char_complete_adjustment.set_can_focus(True)
        self._min_char_complete_adjustment.set_increments(1.0, 1.0)
        self._min_char_complete_adjustment.set_range(1.0, 9.0)
        self._options_grid.attach(
            self._min_char_complete_adjustment, 1, 10, 1, 1)
        self._min_char_complete = itb_util.variant_to_value(
            self._gsettings.get_value('mincharcomplete'))
        if self._min_char_complete:
            self._min_char_complete_adjustment.set_value(
                int(self._min_char_complete))
        else:
            self._min_char_complete_adjustment.set_value(1)
        self._min_char_complete_adjustment.connect(
            'value-changed',
            self.on_min_char_complete_adjustment_value_changed)

        self._debug_level_label = Gtk.Label()
        self._debug_level_label.set_text(
            # Translators: When the debug level is greater than 0,
            # debug information may be printed to the log file and
            # debug information may also be shown graphically.
            _('Debug level:'))
        self._debug_level_label.set_tooltip_text(
            _('When greater than 0, debug information may be '
              + 'printed to the log file and debug information '
              + 'may also be shown graphically.'))
        self._debug_level_label.set_xalign(0)
        self._options_grid.attach(
            self._debug_level_label, 0, 11, 1, 1)

        self._debug_level_adjustment = Gtk.SpinButton()
        self._debug_level_adjustment.set_visible(True)
        self._debug_level_adjustment.set_can_focus(True)
        self._debug_level_adjustment.set_increments(1.0, 1.0)
        self._debug_level_adjustment.set_range(0.0, 255.0)
        self._options_grid.attach(
            self._debug_level_adjustment, 1, 11, 1, 1)
        self._debug_level = itb_util.variant_to_value(
            self._gsettings.get_value('debuglevel'))
        if self._debug_level:
            self._debug_level_adjustment.set_value(
                int(self._debug_level))
        else:
            self._debug_level_adjustment.set_value(0)
        self._debug_level_adjustment.connect(
            'value-changed',
            self.on_debug_level_adjustment_value_changed)

        self._learn_from_file_button = Gtk.Button(
            # Translators: A button used to popup a file selector to
            # choose a text file and learn your writing style by
            # reading that text file.
            label=_('Learn from text file'))
        self._learn_from_file_button.set_tooltip_text(
            _('Learn your style by reading a text file'))
        self._options_grid.attach(
            self._learn_from_file_button, 0, 12, 2, 1)
        self._learn_from_file_button.connect(
            'clicked', self.on_learn_from_file_clicked)

        self._delete_learned_data_button = Gtk.Button(
            # Translators: A button used to delete all personal
            # language data learned from typing or from reading files.
            label=_('Delete learned data'))
        self._delete_learned_data_button.set_tooltip_text(
            _('Delete all personal language data learned from '
              + 'typing or from reading files'))
        self._options_grid.attach(
            self._delete_learned_data_button, 0, 13, 2, 1)
        self._delete_learned_data_button.connect(
            'clicked', self.on_delete_learned_data_clicked)

        self._dictionaries_label = Gtk.Label()
        self._dictionaries_label.set_text(
            # Translators: This is the header of the list of
            # dictionaries which are currently set up to be used by
            # ibus-typing-booster.
            '<b>' +_('Use dictionaries for the following languages:') + '</b>')
        self._dictionaries_label.set_use_markup(True)
        margin = 5
        self._dictionaries_label.set_margin_start(margin)
        self._dictionaries_label.set_margin_end(margin)
        self._dictionaries_label.set_margin_top(margin)
        self._dictionaries_label.set_margin_bottom(margin)
        self._dictionaries_label.set_hexpand(False)
        self._dictionaries_label.set_vexpand(False)
        self._dictionaries_label.set_xalign(0)
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._dictionaries_label, False, False, 0)
        self._dictionaries_scroll = Gtk.ScrolledWindow()
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._dictionaries_scroll, True, True, 0)
        self._dictionaries_install_missing_button = Gtk.Button(
            # Translators: A button used to try to install the
            # dictionaries which are setup here but not installed
            label=_('Install missing dictionaries'))
        self._dictionaries_install_missing_button.set_tooltip_text(
            _('Install the dictionaries which are '
              + 'setup here but not installed'))
        self._dictionaries_install_missing_button.connect(
            'clicked', self.on_install_missing_dictionaries)
        self._dictionaries_action_area = Gtk.ButtonBox()
        self._dictionaries_action_area.set_can_focus(False)
        self._dictionaries_action_area.set_layout(Gtk.ButtonBoxStyle.START)
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._dictionaries_action_area, False, False, 0)
        self._dictionaries_add_button = Gtk.Button()
        self._dictionaries_add_button_label = Gtk.Label()
        self._dictionaries_add_button_label.set_text(
            '<span size="xx-large"><b>+</b></span>')
        self._dictionaries_add_button_label.set_use_markup(True)
        self._dictionaries_add_button.add(
            self._dictionaries_add_button_label)
        self._dictionaries_add_button.set_tooltip_text(
            _('Add a dictionary'))
        self._dictionaries_add_button.connect(
            'clicked', self.on_dictionaries_add_button_clicked)
        self._dictionaries_remove_button = Gtk.Button()
        self._dictionaries_remove_button_label = Gtk.Label()
        self._dictionaries_remove_button_label.set_text(
            '<span size="xx-large"><b>−</b></span>')
        self._dictionaries_remove_button_label.set_use_markup(True)
        self._dictionaries_remove_button.add(
            self._dictionaries_remove_button_label)
        self._dictionaries_remove_button.set_tooltip_text(
            _('Remove a dictionary'))
        self._dictionaries_remove_button.connect(
            'clicked', self.on_dictionaries_remove_button_clicked)
        self._dictionaries_remove_button.set_sensitive(False)
        self._dictionaries_up_button = Gtk.Button()
        self._dictionaries_up_button_label = Gtk.Label()
        self._dictionaries_up_button_label.set_text(
            '<span size="xx-large"><b>↑</b></span>')
        self._dictionaries_up_button_label.set_use_markup(True)
        self._dictionaries_up_button.add(self._dictionaries_up_button_label)
        self._dictionaries_up_button.set_tooltip_text(
            _('Move dictionary up'))
        self._dictionaries_up_button.connect(
            'clicked', self.on_dictionaries_up_button_clicked)
        self._dictionaries_up_button.set_sensitive(False)
        self._dictionaries_down_button = Gtk.Button()
        self._dictionaries_down_button_label = Gtk.Label()
        self._dictionaries_down_button_label.set_text(
            '<span size="xx-large"><b>↓</b></span>')
        self._dictionaries_down_button_label.set_use_markup(True)
        self._dictionaries_down_button.add(
            self._dictionaries_down_button_label)
        self._dictionaries_down_button.set_tooltip_text(
            _('Move dictionary down'))
        self._dictionaries_down_button.connect(
            'clicked', self.on_dictionaries_down_button_clicked)
        self._dictionaries_down_button.set_sensitive(False)
        self._dictionaries_action_area.add(self._dictionaries_add_button)
        self._dictionaries_action_area.add(self._dictionaries_remove_button)
        self._dictionaries_action_area.add(self._dictionaries_up_button)
        self._dictionaries_action_area.add(self._dictionaries_down_button)
        self._dictionaries_action_area.add(
            self._dictionaries_install_missing_button)
        self._dictionaries_listbox_selected_dictionary_name = ''
        self._dictionaries_listbox_selected_dictionary_index = -1
        self._dictionary_names = []
        self._dictionaries_listbox = None
        self._dictionaries_add_listbox = None
        self._dictionaries_add_popover = None
        self._dictionaries_add_popover_scroll = None
        self._fill_dictionaries_listbox()

        self._input_methods_label = Gtk.Label()
        self._input_methods_label.set_text(
            # Translators: This is the header of the list of input
            # methods which are currently set up to be used by
            # ibus-typing-booster.
            '<b>' + _('Use the following input methods:') + '</b>')
        self._input_methods_label.set_use_markup(True)
        margin = 5
        self._input_methods_label.set_margin_start(margin)
        self._input_methods_label.set_margin_end(margin)
        self._input_methods_label.set_margin_top(margin)
        self._input_methods_label.set_margin_bottom(margin)
        self._input_methods_label.set_hexpand(False)
        self._input_methods_label.set_vexpand(False)
        self._input_methods_label.set_xalign(0)
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._input_methods_label, False, False, 0)
        self._input_methods_scroll = Gtk.ScrolledWindow()
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._input_methods_scroll, True, True, 0)
        self._input_methods_action_area = Gtk.ButtonBox()
        self._input_methods_action_area.set_can_focus(False)
        self._input_methods_action_area.set_layout(Gtk.ButtonBoxStyle.START)
        self._dictionaries_and_input_methods_vbox.pack_start(
            self._input_methods_action_area, False, False, 0)
        self._input_methods_add_button = Gtk.Button()
        self._input_methods_add_button_label = Gtk.Label()
        self._input_methods_add_button_label.set_text(
            '<span size="xx-large"><b>+</b></span>')
        self._input_methods_add_button_label.set_use_markup(True)
        self._input_methods_add_button.add(
            self._input_methods_add_button_label)
        self._input_methods_add_button.set_tooltip_text(
            _('Add an input method'))
        self._input_methods_add_button.connect(
            'clicked', self.on_input_methods_add_button_clicked)
        self._input_methods_add_button.set_sensitive(False)
        self._input_methods_remove_button = Gtk.Button()
        self._input_methods_remove_button_label = Gtk.Label()
        self._input_methods_remove_button_label.set_text(
            '<span size="xx-large"><b>−</b></span>')
        self._input_methods_remove_button_label.set_use_markup(True)
        self._input_methods_remove_button.add(
            self._input_methods_remove_button_label)
        self._input_methods_remove_button.set_tooltip_text(
            _('Remove an input method'))
        self._input_methods_remove_button.connect(
            'clicked', self.on_input_methods_remove_button_clicked)
        self._input_methods_remove_button.set_sensitive(False)
        self._input_methods_up_button = Gtk.Button()
        self._input_methods_up_button_label = Gtk.Label()
        self._input_methods_up_button_label.set_text(
            '<span size="xx-large"><b>↑</b></span>')
        self._input_methods_up_button_label.set_use_markup(True)
        self._input_methods_up_button.add(
            self._input_methods_up_button_label)
        self._input_methods_up_button.set_tooltip_text(
            _('Move input method up'))
        self._input_methods_up_button.connect(
            'clicked', self.on_input_methods_up_button_clicked)
        self._input_methods_up_button.set_sensitive(False)
        self._input_methods_down_button = Gtk.Button()
        self._input_methods_down_button_label = Gtk.Label()
        self._input_methods_down_button_label.set_text(
            '<span size="xx-large"><b>↓</b></span>')
        self._input_methods_down_button_label.set_use_markup(True)
        self._input_methods_down_button.add(
            self._input_methods_down_button_label)
        self._input_methods_down_button.set_tooltip_text(
            _('Move input method down'))
        self._input_methods_down_button.connect(
            'clicked', self.on_input_methods_down_button_clicked)
        self._input_methods_down_button.set_sensitive(False)
        self._input_methods_help_button = Gtk.Button(
            # Translators: A button to display some help showing how
            # to use the input method selected in the list of input
            # methods.
            label=_('Input Method Help'))
        self._input_methods_help_button.set_tooltip_text(
            _('Display some help showing how to use the '
              + 'input method selected above.'))
        self._input_methods_help_button.connect(
            'clicked', self.on_input_methods_help_button_clicked)
        self._input_methods_help_button.set_sensitive(False)
        self._input_methods_action_area.add(self._input_methods_add_button)
        self._input_methods_action_area.add(self._input_methods_remove_button)
        self._input_methods_action_area.add(self._input_methods_up_button)
        self._input_methods_action_area.add(self._input_methods_down_button)
        self._input_methods_action_area.add(self._input_methods_help_button)
        self._input_methods_listbox_selected_ime_name = ''
        self._input_methods_listbox_selected_ime_index = -1
        self._current_imes = []
        self._input_methods_listbox = None
        self._input_methods_add_listbox = None
        self._input_methods_add_popover = None
        self._input_methods_add_popover_scroll = None
        self._fill_input_methods_listbox()

        self._shortcut_label = Gtk.Label()
        self._shortcut_label.set_text(_('Enter shortcut here:'))
        self._shortcut_label.set_hexpand(False)
        self._shortcut_label.set_vexpand(False)
        self._shortcut_label.set_xalign(0)
        self._custom_shortcuts_grid.attach(
            self._shortcut_label, 0, 0, 3, 1)

        self._shortcut_entry = Gtk.Entry()
        self._shortcut_entry.set_visible(True)
        self._shortcut_entry.set_can_focus(True)
        self._shortcut_entry.set_hexpand(False)
        self._shortcut_entry.set_vexpand(False)
        self._custom_shortcuts_grid.attach(
            self._shortcut_entry, 0, 1, 3, 1)

        self._shortcut_expansion_label = Gtk.Label()
        self._shortcut_expansion_label.set_text(
            _('Enter shortcut expansion here:'))
        self._shortcut_expansion_label.set_hexpand(False)
        self._shortcut_expansion_label.set_vexpand(False)
        self._shortcut_expansion_label.set_xalign(0)
        self._custom_shortcuts_grid.attach(
            self._shortcut_expansion_label, 0, 2, 3, 1)

        self._shortcut_expansion_entry = Gtk.Entry()
        self._shortcut_expansion_entry.set_visible(True)
        self._shortcut_expansion_entry.set_can_focus(True)
        self._shortcut_expansion_entry.set_hexpand(False)
        self._shortcut_expansion_entry.set_vexpand(False)
        self._custom_shortcuts_grid.attach(
            self._shortcut_expansion_entry, 0, 3, 3, 1)

        self._shortcut_clear_button = Gtk.Button(
            label=_('Clear input'))
        self._shortcut_clear_button.set_receives_default(False)
        self._shortcut_clear_button.set_hexpand(False)
        self._shortcut_clear_button.set_vexpand(False)
        self._custom_shortcuts_grid.attach(
            self._shortcut_clear_button, 0, 4, 1, 1)
        self._shortcut_clear_button.connect(
            'clicked', self.on_shortcut_clear_clicked)

        self._shortcut_delete_button = Gtk.Button(
            label=_('Delete shortcut'))
        self._shortcut_delete_button.set_receives_default(False)
        self._shortcut_delete_button.set_hexpand(False)
        self._shortcut_delete_button.set_vexpand(False)
        self._custom_shortcuts_grid.attach(
            self._shortcut_delete_button, 1, 4, 1, 1)
        self._shortcut_delete_button.connect(
            'clicked', self.on_shortcut_delete_clicked)

        self._shortcut_add_button = Gtk.Button(
            label=_('Add shortcut'))
        self._shortcut_add_button.set_receives_default(False)
        self._shortcut_add_button.set_hexpand(False)
        self._shortcut_add_button.set_vexpand(False)
        self._custom_shortcuts_grid.attach(
            self._shortcut_add_button, 2, 4, 1, 1)
        self._shortcut_add_button.connect(
            'clicked', self.on_shortcut_add_clicked)

        self._shortcut_treeview_scroll = Gtk.ScrolledWindow()
        self._shortcut_treeview_scroll.set_can_focus(False)
        self._shortcut_treeview_scroll.set_hexpand(False)
        self._shortcut_treeview_scroll.set_vexpand(True)
        #self._shortcut_treeview_scroll.set_shadow_type(in)
        self._shortcut_treeview = Gtk.TreeView()
        self._shortcut_treeview_model = Gtk.ListStore(str, str)
        self._shortcut_treeview.set_model(self._shortcut_treeview_model)
        current_shortcuts = self.tabsqlitedb.list_user_shortcuts()
        for i, shortcut in enumerate(current_shortcuts):
            self._shortcut_treeview_model.append(shortcut)
        self._shortcut_treeview.append_column(
            Gtk.TreeViewColumn(
                # Translators: Column heading of the table listing the
                # existing shortcuts
                _('Shortcut'),
                Gtk.CellRendererText(),
                text=0))
        self._shortcut_treeview.append_column(
            Gtk.TreeViewColumn(
                # Translators: Column heading of the table listing the
                # existing shortcuts
                _('Shortcut expansion'),
                Gtk.CellRendererText(),
                text=1))
        self._shortcut_treeview.get_selection().connect(
            'changed', self.on_shortcut_selected)
        self._shortcut_treeview_scroll.add(self._shortcut_treeview)
        self._custom_shortcuts_grid.attach(
            self._shortcut_treeview_scroll, 0, 5, 3, 10)

        self._keybindings_label = Gtk.Label()
        self._keybindings_label.set_text(
            '<b>' + _('Current key bindings:') + '</b>')
        self._keybindings_label.set_use_markup(True)
        self._keybindings_label.set_margin_start(margin)
        self._keybindings_label.set_margin_end(margin)
        self._keybindings_label.set_margin_top(margin)
        self._keybindings_label.set_margin_bottom(margin)
        self._keybindings_label.set_hexpand(False)
        self._keybindings_label.set_vexpand(False)
        self._keybindings_label.set_xalign(0)
        self._keybindings_treeview_scroll = Gtk.ScrolledWindow()
        self._keybindings_treeview_scroll.set_can_focus(False)
        self._keybindings_treeview_scroll.set_hexpand(False)
        self._keybindings_treeview_scroll.set_vexpand(True)
        #self._keybindings_treeview_scroll.set_shadow_type(in)
        self._keybindings_treeview = Gtk.TreeView()
        self._keybindings_treeview_model = Gtk.ListStore(str, str)
        self._keybindings_treeview.set_model(self._keybindings_treeview_model)
        for command in sorted(self._keybindings):
            self._keybindings_treeview_model.append(
                (command, repr(self._keybindings[command])))
        self._keybindings_treeview.append_column(
            Gtk.TreeViewColumn(
                # Translators: Column heading of the table listing the
                # existing key bindings
                _('Command'),
                Gtk.CellRendererText(),
                text=0))
        self._keybindings_treeview.append_column(
            Gtk.TreeViewColumn(
                # Translators: Column heading of the table listing the
                # existing key bindings
                _('Key bindings'),
                Gtk.CellRendererText(),
                text=1))
        self._keybindings_treeview.get_selection().connect(
            'changed', self.on_keybindings_treeview_row_selected)
        self._keybindings_treeview.connect(
            'row-activated', self.on_keybindings_treeview_row_activated)
        self._keybindings_treeview_scroll.add(self._keybindings_treeview)
        self._keybindings_vbox.pack_start(
            self._keybindings_label, False, False, 0)
        self._keybindings_vbox.pack_start(
            self._keybindings_treeview_scroll, True, True, 0)
        self._keybindings_action_area = Gtk.ButtonBox()
        self._keybindings_action_area.set_can_focus(False)
        self._keybindings_action_area.set_layout(Gtk.ButtonBoxStyle.START)
        self._keybindings_vbox.pack_start(
            self._keybindings_action_area, False, False, 0)
        self._keybindings_edit_button = Gtk.Button()
        self._keybindings_edit_button_label = Gtk.Label()
        self._keybindings_edit_button_label.set_text(
            _('Edit'))
        self._keybindings_edit_button.add(
            self._keybindings_edit_button_label)
        self._keybindings_edit_button.set_tooltip_text(
            _('Edit the key bindings for the selected command'))
        self._keybindings_edit_button.set_sensitive(False)
        self._keybindings_edit_button.connect(
            'clicked', self.on_keybindings_edit_button_clicked)
        self._keybindings_default_button = Gtk.Button()
        self._keybindings_default_button_label = Gtk.Label()
        self._keybindings_default_button_label.set_text(
            _('Set to default'))
        self._keybindings_default_button.add(
            self._keybindings_default_button_label)
        self._keybindings_default_button.set_tooltip_text(
            _('Set default key bindings for the selected command'))
        self._keybindings_default_button.set_sensitive(False)
        self._keybindings_default_button.connect(
            'clicked', self.on_keybindings_default_button_clicked)
        self._keybindings_all_default_button = Gtk.Button()
        self._keybindings_all_default_button_label = Gtk.Label()
        self._keybindings_all_default_button_label.set_text(
            _('Set all to default'))
        self._keybindings_all_default_button.add(
            self._keybindings_all_default_button_label)
        self._keybindings_all_default_button.set_tooltip_text(
            _('Set default key bindings for all commands'))
        self._keybindings_all_default_button.set_sensitive(True)
        self._keybindings_all_default_button.connect(
            'clicked', self.on_keybindings_all_default_button_clicked)
        self._keybindings_action_area.add(self._keybindings_edit_button)
        self._keybindings_action_area.add(self._keybindings_default_button)
        self._keybindings_action_area.add(self._keybindings_all_default_button)
        self._keybindings_selected_command = ''
        self._keybindings_edit_popover_selected_keybinding = ''
        self._keybindings_edit_popover_listbox = None
        self._keybindings_edit_popover = None
        self._keybindings_edit_popover_scroll = None
        self._keybindings_edit_popover_add_button = None
        self._keybindings_edit_popover_remove_button = None
        self._keybindings_edit_popover_default_button = None

        self._show_number_of_candidates_checkbutton = Gtk.CheckButton(
            # Translators: Checkbox to choose whether to display how
            # many candidates there are and which one is selected on
            # top of the list of candidates.
            label=_('Display total number of candidates'))
        self._show_number_of_candidates_checkbutton.set_tooltip_text(
            _('Display how many candidates there are and which '
              + 'one is selected on top of the list of candidates.'))
        self._show_number_of_candidates_checkbutton.connect(
            'clicked', self.on_show_number_of_candidates_checkbutton)
        self._appearance_grid.attach(
            self._show_number_of_candidates_checkbutton, 0, 0, 1, 1)
        self._show_number_of_candidates = itb_util.variant_to_value(
            self._gsettings.get_value('shownumberofcandidates'))
        if self._show_number_of_candidates is None:
            self._show_number_of_candidates = False
        if  self._show_number_of_candidates is True:
            self._show_number_of_candidates_checkbutton.set_active(True)

        self._show_status_info_in_auxiliary_text_checkbutton = Gtk.CheckButton(
            # Translators: Checkbox to choose whether to show above
            # the candidate list whether “Emoji prediction” mode and
            # “Off the record” mode are on or off and show which input
            # method is currently used for the preëdit. The auxiliary
            # text is an optional line of text displayed above the
            # candidate list.
            label=_('Show status info in auxiliary text'))
        self._show_status_info_in_auxiliary_text_checkbutton.set_tooltip_text(
            _('Show in the auxiliary text whether “Emoji prediction”  '
              + 'mode and “Off the record”  mode are on or off '
              + 'and show which input method is currently used '
              + 'for the preëdit. The auxiliary text is an '
              + 'optional line of text displayed above the '
              + 'candidate list.'))
        self._show_status_info_in_auxiliary_text_checkbutton.connect(
            'clicked', self.on_show_status_info_in_auxiliary_text_checkbutton)
        self._appearance_grid.attach(
            self._show_status_info_in_auxiliary_text_checkbutton, 1, 0, 1, 1)
        self._show_status_info_in_auxiliary_text = itb_util.variant_to_value(
            self._gsettings.get_value('showstatusinfoinaux'))
        if self._show_status_info_in_auxiliary_text is None:
            self._show_status_info_in_auxiliary_text = False
        if self._show_status_info_in_auxiliary_text is True:
            self._show_status_info_in_auxiliary_text_checkbutton.set_active(
                True)

        self._page_size_label = Gtk.Label()
        # Translators: Here one can choose how many suggestion
        # candidates to show in one page of the candidate list.
        self._page_size_label.set_text(_('Candidate window page size:'))
        self._page_size_label.set_tooltip_text(
            _('How many suggestion candidates to show in '
              + 'one page of the candidate list.'))
        self._page_size_label.set_xalign(0)
        self._appearance_grid.attach(
            self._page_size_label, 0, 1, 1, 1)

        self._page_size_adjustment = Gtk.SpinButton()
        self._page_size_adjustment.set_visible(True)
        self._page_size_adjustment.set_can_focus(True)
        self._page_size_adjustment.set_increments(1.0, 1.0)
        self._page_size_adjustment.set_range(1.0, 9.0)
        self._appearance_grid.attach(
            self._page_size_adjustment, 1, 1, 1, 1)
        self._page_size = itb_util.variant_to_value(
            self._gsettings.get_value('pagesize'))
        if self._page_size:
            self._page_size_adjustment.set_value(int(self._page_size))
        else:
            self._page_size_adjustment.set_value(6)
        self._page_size_adjustment.connect(
            'value-changed', self.on_page_size_adjustment_value_changed)

        self._lookup_table_orientation_label = Gtk.Label()
        self._lookup_table_orientation_label.set_text(
            # Translators: A combobox to choose whether the candidate
            # window should be drawn horizontally or vertically.
            _('Candidate window orientation'))
        self._lookup_table_orientation_label.set_tooltip_text(
            _('Whether the candidate window should be '
              + 'drawn horizontally or vertically.'))
        self._lookup_table_orientation_label.set_xalign(0)
        self._appearance_grid.attach(
            self._lookup_table_orientation_label, 0, 2, 1, 1)

        self._lookup_table_orientation_combobox = Gtk.ComboBox()
        self._lookup_table_orientation_store = Gtk.ListStore(str, int)
        self._lookup_table_orientation_store.append(
            [_('Horizontal'), IBus.Orientation.HORIZONTAL])
        self._lookup_table_orientation_store.append(
            [_('Vertical'), IBus.Orientation.VERTICAL])
        self._lookup_table_orientation_store.append(
            [_('System default'), IBus.Orientation.SYSTEM])
        self._lookup_table_orientation_combobox.set_model(
            self._lookup_table_orientation_store)
        renderer_text = Gtk.CellRendererText()
        self._lookup_table_orientation_combobox.pack_start(
            renderer_text, True)
        self._lookup_table_orientation_combobox.add_attribute(
            renderer_text, "text", 0)
        self._lookup_table_orientation = itb_util.variant_to_value(
            self._gsettings.get_value('lookuptableorientation'))
        if self._lookup_table_orientation is None:
            self._lookup_table_orientation = IBus.Orientation.VERTICAL
        for i, item in enumerate(self._lookup_table_orientation_store):
            if self._lookup_table_orientation == item[1]:
                self._lookup_table_orientation_combobox.set_active(i)
        self._appearance_grid.attach(
            self._lookup_table_orientation_combobox, 1, 2, 1, 1)
        self._lookup_table_orientation_combobox.connect(
            "changed",
            self.on_lookup_table_orientation_combobox_changed)

        self._preedit_underline_label = Gtk.Label()
        self._preedit_underline_label.set_text(
            # Translators: A combobox to choose the style of
            # underlining for the preedit.
            _('Preedit underline'))
        self._preedit_underline_label.set_tooltip_text(
            _('Which style of underlining to use for the preedit.'))
        self._preedit_underline_label.set_xalign(0)
        self._appearance_grid.attach(
            self._preedit_underline_label, 0, 3, 1, 1)

        self._preedit_underline_combobox = Gtk.ComboBox()
        self._preedit_underline_store = Gtk.ListStore(str, int)
        self._preedit_underline_store.append(
            # Translators: This is the setting to use no underline
            # at all for the preedit.
            [_('None'), IBus.AttrUnderline.NONE])
        self._preedit_underline_store.append(
            # Translators: This is the setting to use a single
            # underline for the preedit.
            [_('Single'), IBus.AttrUnderline.SINGLE])
        self._preedit_underline_store.append(
            # Translators: This is the setting to use a double
            # underline for the preedit.
            [_('Double'), IBus.AttrUnderline.DOUBLE])
        self._preedit_underline_store.append(
            # Translators: This is the setting to use a low
            # underline for the preedit.
            [_('Low'), IBus.AttrUnderline.LOW])
        self._preedit_underline_combobox.set_model(
            self._preedit_underline_store)
        renderer_text = Gtk.CellRendererText()
        self._preedit_underline_combobox.pack_start(
            renderer_text, True)
        self._preedit_underline_combobox.add_attribute(
            renderer_text, "text", 0)
        self._preedit_underline = itb_util.variant_to_value(
            self._gsettings.get_value('preeditunderline'))
        if self._preedit_underline is None:
            self._preedit_underline = IBus.AttrUnderline.SINGLE
        for i, item in enumerate(self._preedit_underline_store):
            if self._preedit_underline == item[1]:
                self._preedit_underline_combobox.set_active(i)
        self._appearance_grid.attach(
            self._preedit_underline_combobox, 1, 3, 1, 1)
        self._preedit_underline_combobox.connect(
            "changed",
            self.on_preedit_underline_combobox_changed)

        self._preedit_style_only_when_lookup_checkbutton = Gtk.CheckButton(
            # Translators: Checkbox to choose whether a preedit style
            # like underlining will only be used if lookup is
            # enabled. The lookup can be disabled because one uses the
            # option to enable lookup only when a key is pressed or
            # because one uses the option to require a minimum number
            # of characters before a lookup is done.
            label=_('Use preedit style only if lookup is enabled'))
        self._preedit_style_only_when_lookup_checkbutton.set_tooltip_text(
            _('If this option is on, a preedit style like underlining '
              + 'will only be used if lookup is enabled. '
              + 'The lookup can be disabled because one uses the option '
              + 'to enable lookup only when a key is pressed or '
              + 'because one uses the option to require a minimum '
              + 'number of characters before a lookup is done.'))
        self._preedit_style_only_when_lookup_checkbutton.connect(
            'clicked', self.on_preedit_style_only_when_lookup_checkbutton)
        self._appearance_grid.attach(
            self._preedit_style_only_when_lookup_checkbutton, 0, 4, 2, 1)
        self._preedit_style_only_when_lookup = itb_util.variant_to_value(
            self._gsettings.get_value('preeditstyleonlywhenlookup'))
        if self._preedit_style_only_when_lookup is None:
            self._preedit_style_only_when_lookup = False
        if self._preedit_style_only_when_lookup is True:
            self._preedit_style_only_when_lookup_checkbutton.set_active(True)

        self._color_inline_completion_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # custom color is used for suggestions shown inline.
            label=_('Use color for inline completion'))
        self._color_inline_completion_checkbutton.set_tooltip_text(
            _('Here you can choose whether a custom color '
              + 'is used for a suggestion shown inline.'))
        self._color_inline_completion_checkbutton.set_hexpand(False)
        self._color_inline_completion_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._color_inline_completion_checkbutton, 0, 5, 1, 1)
        self._color_inline_completion = itb_util.variant_to_value(
            self._gsettings.get_value('colorinlinecompletion'))
        if self._color_inline_completion is None:
            self._color_inline_completion = True
        self._color_inline_completion_checkbutton.set_active(
            self._color_inline_completion)
        self._color_inline_completion_checkbutton.connect(
            'clicked', self.on_color_inline_completion_checkbutton)
        self._color_inline_completion_rgba_colorbutton = Gtk.ColorButton()
        margin = 0
        self._color_inline_completion_rgba_colorbutton.set_margin_start(
            margin)
        self._color_inline_completion_rgba_colorbutton.set_margin_end(
            margin)
        self._color_inline_completion_rgba_colorbutton.set_margin_top(
            margin)
        self._color_inline_completion_rgba_colorbutton.set_margin_bottom(
            margin)
        self._color_inline_completion_rgba_colorbutton.set_hexpand(False)
        self._color_inline_completion_rgba_colorbutton.set_vexpand(False)
        self._color_inline_completion_rgba_colorbutton.set_title(
            # Translators: Used in the title bar of the colour chooser
            # dialog window where one can choose a custom colour for
            # inline completion.
            _('Choose color for inline completion'))
        self._color_inline_completion_rgba_colorbutton.set_tooltip_text(
            _('Here you can specify which color to use for '
              + 'inline completion. This setting only has an '
              + 'effect if the use of color for inline completion '
              + 'is enabled and inline completion is enabled.'))
        self._color_inline_completion_string = itb_util.variant_to_value(
            self._gsettings.get_value('colorinlinecompletionstring'))
        gdk_rgba = Gdk.RGBA()
        gdk_rgba.parse(self._color_inline_completion_string)
        self._color_inline_completion_rgba_colorbutton.set_rgba(gdk_rgba)
        self._appearance_grid.attach(
            self._color_inline_completion_rgba_colorbutton, 1, 5, 1, 1)
        self._color_inline_completion_rgba_colorbutton.set_sensitive(
            self._color_inline_completion)
        self._color_inline_completion_rgba_colorbutton.connect(
            'color-set', self.on_color_inline_completion_color_set)

        self._color_userdb_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # custom color is used for suggestions coming from the
            # user database.
            label=_('Use color for user database suggestions'))
        self._color_userdb_checkbutton.set_tooltip_text(
            _('Here you can choose whether a custom color is used '
              + 'for candidates in the lookup table which come '
              + 'from the user database.'))
        self._color_userdb_checkbutton.set_hexpand(False)
        self._color_userdb_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._color_userdb_checkbutton, 0, 6, 1, 1)
        self._color_userdb = itb_util.variant_to_value(
            self._gsettings.get_value('coloruserdb'))
        if self._color_userdb is None:
            self._color_userdb = False
        self._color_userdb_checkbutton.set_active(self._color_userdb)
        self._color_userdb_checkbutton.connect(
            'clicked', self.on_color_userdb_checkbutton)
        self._color_userdb_rgba_colorbutton = Gtk.ColorButton()
        margin = 0
        self._color_userdb_rgba_colorbutton.set_margin_start(margin)
        self._color_userdb_rgba_colorbutton.set_margin_end(margin)
        self._color_userdb_rgba_colorbutton.set_margin_top(margin)
        self._color_userdb_rgba_colorbutton.set_margin_bottom(margin)
        self._color_userdb_rgba_colorbutton.set_hexpand(False)
        self._color_userdb_rgba_colorbutton.set_vexpand(False)
        self._color_userdb_rgba_colorbutton.set_title(
            # Translators: Used in the title bar of the colour chooser
            # dialog window where one can choose a custom colour for
            # suggestions from the user database.
            _('Choose color for user database suggestions'))
        self._color_userdb_rgba_colorbutton.set_tooltip_text(
            _('Here you can specify which color to use for '
              + 'candidates in the lookup table which come '
              + 'from the user database. This setting only '
              + 'has an effect if the use of color for '
              + 'candidates from the user database is enabled.'))
        self._color_userdb_string = itb_util.variant_to_value(
            self._gsettings.get_value('coloruserdbstring'))
        gdk_rgba = Gdk.RGBA()
        gdk_rgba.parse(self._color_userdb_string)
        self._color_userdb_rgba_colorbutton.set_rgba(gdk_rgba)
        self._appearance_grid.attach(
            self._color_userdb_rgba_colorbutton, 1, 6, 1, 1)
        self._color_userdb_rgba_colorbutton.set_sensitive(
            self._color_userdb)
        self._color_userdb_rgba_colorbutton.connect(
            'color-set', self.on_color_userdb_color_set)

        self._color_spellcheck_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # custom color is used for spellchecking suggestions.
            label=_('Use color for spellchecking suggestions'))
        self._color_spellcheck_checkbutton.set_tooltip_text(
            _('Here you can choose whether a custom color '
              + 'is used for candidates in the lookup table '
              + 'which come from spellchecking.'))
        self._color_spellcheck_checkbutton.set_hexpand(False)
        self._color_spellcheck_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._color_spellcheck_checkbutton, 0, 7, 1, 1)
        self._color_spellcheck = itb_util.variant_to_value(
            self._gsettings.get_value('colorspellcheck'))
        if self._color_spellcheck is None:
            self._color_spellcheck = False
        self._color_spellcheck_checkbutton.set_active(self._color_spellcheck)
        self._color_spellcheck_checkbutton.connect(
            'clicked', self.on_color_spellcheck_checkbutton)
        self._color_spellcheck_rgba_colorbutton = Gtk.ColorButton()
        margin = 0
        self._color_spellcheck_rgba_colorbutton.set_margin_start(margin)
        self._color_spellcheck_rgba_colorbutton.set_margin_end(margin)
        self._color_spellcheck_rgba_colorbutton.set_margin_top(margin)
        self._color_spellcheck_rgba_colorbutton.set_margin_bottom(margin)
        self._color_spellcheck_rgba_colorbutton.set_hexpand(False)
        self._color_spellcheck_rgba_colorbutton.set_vexpand(False)
        self._color_spellcheck_rgba_colorbutton.set_title(
            # Translators: Used in the title bar of the colour chooser
            # dialog window where one can choose a custom colour for
            # spellchecking suggestions.
            _('Choose color for spellchecking suggestions'))
        self._color_spellcheck_rgba_colorbutton.set_tooltip_text(
            _('Here you can specify which color to use for '
              + 'candidates in the lookup table which come '
              + 'from spellchecking. This setting only has '
              + 'an effect if the use of color for candidates '
              + 'from spellchecking is enabled.'))
        self._color_spellcheck_string = itb_util.variant_to_value(
            self._gsettings.get_value('colorspellcheckstring'))
        gdk_rgba = Gdk.RGBA()
        gdk_rgba.parse(self._color_spellcheck_string)
        self._color_spellcheck_rgba_colorbutton.set_rgba(gdk_rgba)
        self._appearance_grid.attach(
            self._color_spellcheck_rgba_colorbutton, 1, 7, 1, 1)
        self._color_spellcheck_rgba_colorbutton.set_sensitive(
            self._color_spellcheck)
        self._color_spellcheck_rgba_colorbutton.connect(
            'color-set', self.on_color_spellcheck_color_set)

        self._color_dictionary_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # custom color is used for suggestions coming from a
            # dictionary.
            label=_('Use color for dictionary suggestions'))
        self._color_dictionary_checkbutton.set_tooltip_text(
            _('Here you can choose whether a custom color is '
              + 'used for candidates in the lookup table '
              + 'which come from a dictionary.'))
        self._color_dictionary_checkbutton.set_hexpand(False)
        self._color_dictionary_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._color_dictionary_checkbutton, 0, 8, 1, 1)
        self._color_dictionary = itb_util.variant_to_value(
            self._gsettings.get_value('colordictionary'))
        if self._color_dictionary is None:
            self._color_dictionary = False
        self._color_dictionary_checkbutton.set_active(self._color_dictionary)
        self._color_dictionary_checkbutton.connect(
            'clicked', self.on_color_dictionary_checkbutton)
        self._color_dictionary_rgba_colorbutton = Gtk.ColorButton()
        margin = 0
        self._color_dictionary_rgba_colorbutton.set_margin_start(margin)
        self._color_dictionary_rgba_colorbutton.set_margin_end(margin)
        self._color_dictionary_rgba_colorbutton.set_margin_top(margin)
        self._color_dictionary_rgba_colorbutton.set_margin_bottom(margin)
        self._color_dictionary_rgba_colorbutton.set_hexpand(False)
        self._color_dictionary_rgba_colorbutton.set_vexpand(False)
        self._color_dictionary_rgba_colorbutton.set_title(
            # Translators: Used in the title bar of the colour chooser
            # dialog window where one can choose a custom colour for
            # suggestions from a dictionary.
            _('Choose color for dictionary suggestions'))
        self._color_dictionary_rgba_colorbutton.set_tooltip_text(
            _('Here you can specify which color to use for '
              + 'candidates in the lookup table which come '
              + 'from a dictionary. This setting only has '
              + 'an effect if the use of color for candidates '
              + 'from a dictionary is enabled.'))
        self._color_dictionary_string = itb_util.variant_to_value(
            self._gsettings.get_value('colordictionarystring'))
        gdk_rgba = Gdk.RGBA()
        gdk_rgba.parse(self._color_dictionary_string)
        self._color_dictionary_rgba_colorbutton.set_rgba(gdk_rgba)
        self._appearance_grid.attach(
            self._color_dictionary_rgba_colorbutton, 1, 8, 1, 1)
        self._color_dictionary_rgba_colorbutton.set_sensitive(
            self._color_dictionary)
        self._color_dictionary_rgba_colorbutton.connect(
            'color-set', self.on_color_dictionary_color_set)

        self._label_userdb_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # label is used to mark suggestions coming from the user
            # database in the candidate list.
            label=_('Use label for user database suggestions'))
        self._label_userdb_checkbutton.set_tooltip_text(
            _('Here you can choose whether a label is used '
              + 'for candidates in the lookup table which '
              + 'come from the user database.'))
        self._label_userdb_checkbutton.set_hexpand(False)
        self._label_userdb_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_userdb_checkbutton, 0, 9, 1, 1)
        self._label_userdb = itb_util.variant_to_value(
            self._gsettings.get_value('labeluserdb'))
        if self._label_userdb is None:
            self._label_userdb = False
        self._label_userdb_checkbutton.set_active(self._label_userdb)
        self._label_userdb_checkbutton.connect(
            'clicked', self.on_label_userdb_checkbutton)
        self._label_userdb_entry = Gtk.Entry()
        self._label_userdb_entry.set_visible(True)
        self._label_userdb_entry.set_can_focus(True)
        self._label_userdb_entry.set_hexpand(False)
        self._label_userdb_entry.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_userdb_entry, 1, 9, 1, 1)
        self._label_userdb_string = itb_util.variant_to_value(
            self._gsettings.get_value('labeluserdbstring'))
        if not self._label_userdb_string:
            self._label_userdb_string = ''
        self._label_userdb_entry.set_text(
            self._label_userdb_string)
        self._label_userdb_entry.connect(
            'notify::text', self.on_label_userdb_entry)

        self._label_spellcheck_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # label is used to mark suggestions coming from spellchecking
            # in the candidate list.
            label=_('Use label for spellchecking suggestions'))
        self._label_spellcheck_checkbutton.set_tooltip_text(
            _('Here you can choose whether a label is used '
              + 'for candidates in the lookup table which '
              + 'come from spellchecking.'))
        self._label_spellcheck_checkbutton.set_hexpand(False)
        self._label_spellcheck_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_spellcheck_checkbutton, 0, 10, 1, 1)
        self._label_spellcheck = itb_util.variant_to_value(
            self._gsettings.get_value('labelspellcheck'))
        if self._label_spellcheck is None:
            self._label_spellcheck = False
        self._label_spellcheck_checkbutton.set_active(self._label_spellcheck)
        self._label_spellcheck_checkbutton.connect(
            'clicked', self.on_label_spellcheck_checkbutton)
        self._label_spellcheck_entry = Gtk.Entry()
        self._label_spellcheck_entry.set_visible(True)
        self._label_spellcheck_entry.set_can_focus(True)
        self._label_spellcheck_entry.set_hexpand(False)
        self._label_spellcheck_entry.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_spellcheck_entry, 1, 10, 1, 1)
        self._label_spellcheck_string = itb_util.variant_to_value(
            self._gsettings.get_value('labelspellcheckstring'))
        if not self._label_spellcheck_string:
            self._label_spellcheck_string = ''
        self._label_spellcheck_entry.set_text(
            self._label_spellcheck_string)
        self._label_spellcheck_entry.connect(
            'notify::text', self.on_label_spellcheck_entry)

        self._label_dictionary_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # label is used to mark suggestions coming from a
            # dictionary in the candidate list.
            label=_('Use label for dictionary suggestions'))
        self._label_dictionary_checkbutton.set_tooltip_text(
            _('Here you can choose whether a label is used '
              + 'for candidates in the lookup table which '
              + 'come from a dictionary.'))
        self._label_dictionary_checkbutton.set_hexpand(False)
        self._label_dictionary_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_dictionary_checkbutton, 0, 11, 1, 1)
        self._label_dictionary = itb_util.variant_to_value(
            self._gsettings.get_value('labeldictionary'))
        if self._label_dictionary is None:
            self._label_dictionary = False
        self._label_dictionary_checkbutton.set_active(self._label_dictionary)
        self._label_dictionary_checkbutton.connect(
            'clicked', self.on_label_dictionary_checkbutton)
        self._label_dictionary_entry = Gtk.Entry()
        self._label_dictionary_entry.set_visible(True)
        self._label_dictionary_entry.set_can_focus(True)
        self._label_dictionary_entry.set_hexpand(False)
        self._label_dictionary_entry.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_dictionary_entry, 1, 11, 1, 1)
        self._label_dictionary_string = itb_util.variant_to_value(
            self._gsettings.get_value('labeldictionarystring'))
        if not self._label_dictionary_string:
            self._label_dictionary_string = ''
        self._label_dictionary_entry.set_text(
            self._label_dictionary_string)
        self._label_dictionary_entry.connect(
            'notify::text', self.on_label_dictionary_entry)

        self._label_busy_checkbutton = Gtk.CheckButton(
            # Translators: A checkbox where one can choose whether a
            # label is used to show when ibus-typing-booster is busy.
            label=_('Use a label to indicate busy state'))
        self._label_busy_checkbutton.set_tooltip_text(
            _('Here you can choose whether a label is used '
              + 'to indicate when ibus-typing-booster is busy.'))
        self._label_busy_checkbutton.set_hexpand(False)
        self._label_busy_checkbutton.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_busy_checkbutton, 0, 12, 1, 1)
        self._label_busy = itb_util.variant_to_value(
            self._gsettings.get_value('labelbusy'))
        if self._label_busy is None:
            self._label_busy = True
        self._label_busy_checkbutton.set_active(self._label_busy)
        self._label_busy_checkbutton.connect(
            'clicked', self.on_label_busy_checkbutton)
        self._label_busy_entry = Gtk.Entry()
        self._label_busy_entry.set_visible(True)
        self._label_busy_entry.set_can_focus(True)
        self._label_busy_entry.set_hexpand(False)
        self._label_busy_entry.set_vexpand(False)
        self._appearance_grid.attach(
            self._label_busy_entry, 1, 12, 1, 1)
        self._label_busy_string = itb_util.variant_to_value(
            self._gsettings.get_value('labelbusystring'))
        if not self._label_busy_string:
            self._label_busy_string = ''
        self._label_busy_entry.set_text(
            self._label_busy_string)
        self._label_busy_entry.connect(
            'notify::text', self.on_label_busy_entry)

        self._google_application_credentials_label = Gtk.Label()
        self._google_application_credentials_label.set_text(
            # Translators:
            _('Set “Google application credentials” .json file:'))
        self._google_application_credentials_label.set_tooltip_text(
            _('Full path of the “Google application credentials” .json file.'))
        self._google_application_credentials_label.set_xalign(0)
        self._speech_recognition_grid.attach(
            self._google_application_credentials_label, 0, 0, 1, 1)

        self._google_application_credentials = itb_util.variant_to_value(
            self._gsettings.get_value('googleapplicationcredentials'))
        if not self._google_application_credentials:
            self._google_application_credentials = 'Not set.'
        self._google_application_credentials_button = Gtk.Button()
        self._google_application_credentials_button_box = Gtk.HBox()
        self._google_application_credentials_button_label = Gtk.Label()
        self._google_application_credentials_button_label.set_text(
            self._google_application_credentials)
        self._google_application_credentials_button_label.set_use_markup(True)
        self._google_application_credentials_button_label.set_max_width_chars(40)
        self._google_application_credentials_button_label.set_line_wrap(False)
        self._google_application_credentials_button_label.set_ellipsize(
            Pango.EllipsizeMode.START)
        self._google_application_credentials_button_box.pack_start(
            self._google_application_credentials_button_label, False, False, 0)
        self._google_application_credentials_button.add(
            self._google_application_credentials_button_box)
        self._speech_recognition_grid.attach(
            self._google_application_credentials_button, 1, 0, 1, 1)
        self._google_application_credentials_button.connect(
            'clicked', self.on_google_application_credentials_button)

        self.show_all()

        self._notebook.set_current_page(0) # Has to be after show_all()

    def _fill_dictionaries_listbox_row(self, name):
        '''
        Formats the text of a line in the listbox of configured dictionaries

        Returns a tuple consisting of the formatted line of text
        and a Boolean indicating whether the hunspell dictionary
        is missing.

        :param name: Name of the hunspell dictionary
        :type name: String
        :rtype: (String, Boolean)
        '''
        missing_dictionary = False
        row = name + ' ' # NO-BREAK SPACE as a separator
        flag = itb_util.FLAGS.get(name, '  ')
        row += ' ' + flag
        if IMPORT_LANGTABLE_SUCCESSFUL:
            language_description = langtable.language_name(
                languageId=name,
                languageIdQuery=locale.getlocale(category=locale.LC_MESSAGES)[0])
            if not language_description:
                language_description = langtable.language_name(
                    languageId=name, languageIdQuery='en')
            if language_description:
                language_description = (
                    language_description[0].upper() + language_description[1:])
                row += ' ' + language_description
        row += ':  '
        (dic_path,
         dummy_aff_path) = itb_util.find_hunspell_dictionary(name)
        row += ' ' + _('Spell checking') + ' '
        if dic_path:
            row += '✔️'
        else:
            row += '❌'
            missing_dictionary = True
        row += ' ' + _('Emoji') + ' '
        if itb_emoji.find_cldr_annotation_path(name):
            row += '✔️'
        else:
            row += '❌'
        if self._keybindings['speech_recognition']:
            row += ' ' + _('Speech recognition') + ' '
            if name in itb_util.GOOGLE_SPEECH_TO_TEXT_LANGUAGES:
                row += '✔️'
            else:
                row += '❌'
        return (row, missing_dictionary)

    def _fill_dictionaries_listbox(self):
        '''
        Fill the dictionaries listbox with the list of dictionaries read
        from dconf.
        '''
        for child in self._dictionaries_scroll.get_children():
            self._dictionaries_scroll.remove(child)
        self._dictionaries_listbox = Gtk.ListBox()
        self._dictionaries_scroll.add(self._dictionaries_listbox)
        self._dictionaries_listbox_selected_dictionary_name = ''
        self._dictionaries_listbox_selected_dictionary_index = -1
        self._dictionaries_listbox.set_visible(True)
        self._dictionaries_listbox.set_vexpand(True)
        self._dictionaries_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._dictionaries_listbox.set_activate_on_single_click(True)
        self._dictionaries_listbox.connect(
            'row-selected', self.on_dictionary_selected)
        self._dictionary_names = []
        dictionary = itb_util.variant_to_value(
            self._gsettings.get_value('dictionary'))
        if dictionary:
            names = [x.strip() for x in dictionary.split(',')]
            for name in names:
                if name:
                    self._dictionary_names.append(name)
        if self._dictionary_names == []:
            # There are no dictionaries set in dconf, get a default list of
            # dictionaries from the current effective value of LC_CTYPE:
            self._dictionary_names = itb_util.get_default_dictionaries(
                locale.getlocale(category=locale.LC_CTYPE)[0])
        if len(self._dictionary_names) > itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES:
            sys.stderr.write(
                'Trying to set more than the allowed maximum of %s '
                %itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES
                + 'dictionaries.\n'
                + 'Trying to set: %s\n' %self._dictionary_names
                + 'Really setting: %s\n'
                %self._dictionary_names[:itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES])
            self._dictionary_names = (
                self._dictionary_names[:itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES])
            # Save reduced list of input methods back to settings:
            self._gsettings.set_value(
                'dictionary',
                GLib.Variant.new_string(','.join(self._dictionary_names)))
        missing_dictionaries = False
        for name in self._dictionary_names:
            label = Gtk.Label()
            (text,
             missing_dictionary) = self._fill_dictionaries_listbox_row(name)
            if missing_dictionary:
                missing_dictionaries = True
            label.set_text(html.escape(text))
            label.set_use_markup(True)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._dictionaries_listbox.insert(label, -1)
        self._dictionaries_listbox.show_all()
        self._dictionaries_install_missing_button.set_sensitive(
            missing_dictionaries)
        self._dictionaries_add_button.set_sensitive(
            len(self._dictionary_names) < itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES)

    def _fill_input_methods_listbox_row(self, ime):
        '''
        Formats the text of a line in the listbox of configured input methods

        Returns the formatted line of text.

        :param ime: Name of the input method
        :type ime: String
        :rtype: String
        '''
        row = ime + ' ' # NO-BREAK SPACE as a separator
        # add some spaces for nicer formatting:
        row += ' ' * (20 - len(ime))
        (dummy_path,
         title,
         dummy_description,
         dummy_full_contents,
         error) = itb_util.get_ime_help(ime)
        if title:
            row += '\t' + '(' + title + ')'
        if error:
            row += '\t' + '⚠️ ' + error
        try:
            dummy = Transliterator(ime)
            row += '\t' + '✔️'
        except ValueError as open_error:
            row += '\t' + '❌ ' + str(open_error)
        return row

    def _fill_input_methods_listbox(self):
        '''
        Fill the input methods listbox with the list of input methods read
        from dconf.
        '''
        for child in self._input_methods_scroll.get_children():
            self._input_methods_scroll.remove(child)
        self._input_methods_listbox = Gtk.ListBox()
        self._input_methods_scroll.add(self._input_methods_listbox)
        self._input_methods_listbox_selected_ime_name = ''
        self._input_methods_listbox_selected_ime_index = -1
        self._input_methods_listbox.set_visible(True)
        self._input_methods_listbox.set_vexpand(True)
        self._input_methods_listbox.set_selection_mode(
            Gtk.SelectionMode.SINGLE)
        self._input_methods_listbox.set_activate_on_single_click(True)
        self._input_methods_listbox.connect(
            'row-selected', self.on_input_method_selected)
        self._current_imes = []
        inputmethod = itb_util.variant_to_value(
            self._gsettings.get_value('inputmethod'))
        if inputmethod:
            inputmethods = [re.sub(re.escape('noime'), 'NoIME', x.strip(),
                                   flags=re.IGNORECASE)
                            for x in inputmethod.split(',') if x]
            for ime in inputmethods:
                self._current_imes.append(ime)
        if self._current_imes == []:
            # There is no ime set in dconf, get a default list of
            # input methods for the current effective value of LC_CTYPE:
            self._current_imes = itb_util.get_default_input_methods(
                locale.getlocale(category=locale.LC_CTYPE)[0])
        if len(self._current_imes) > itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS:
            sys.stderr.write(
                'Trying to set more than the allowed maximum of %s '
                %itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS
                + 'input methods.\n'
                + 'Trying to set: %s\n' %self._current_imes
                + 'Really setting: %s\n'
                %self._current_imes[:itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS])
            self._current_imes = (
                self._current_imes[:itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS])
            # Save reduced list of input methods back to settings:
            self._gsettings.set_value(
                'inputmethod',
                GLib.Variant.new_string(','.join(self._current_imes)))
        for ime in self._current_imes:
            label = Gtk.Label()
            label.set_text(html.escape(
                self._fill_input_methods_listbox_row(ime)))
            label.set_use_markup(True)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._input_methods_listbox.insert(label, -1)
        self._input_methods_listbox.show_all()
        self._input_methods_add_button.set_sensitive(
            len(self._current_imes) < itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS)

    def __run_message_dialog(self, message, message_type=Gtk.MessageType.INFO):
        '''Run a dialog to show an error or warning message'''
        dialog = Gtk.MessageDialog(
            flags=Gtk.DialogFlags.MODAL,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            message_format=message)
        dialog.run()
        dialog.destroy()

    def _run_are_you_sure_dialog(self, message):
        '''
        Run a dialog to show a “Are you sure?” message.

        Returns Gtk.ResponseType.OK or Gtk.ResponseType.CANCEL
        :rtype: Gtk.ResponseType (enum)
        '''
        confirm_question = Gtk.Dialog(
            title=_('Are you sure?'),
            parent=self)
        confirm_question.add_button(_('_Cancel'), Gtk.ResponseType.CANCEL)
        confirm_question.add_button(_('_OK'), Gtk.ResponseType.OK)
        box = confirm_question.get_content_area()
        label = Gtk.Label()
        label.set_text(
            '<span size="large" color="#ff0000"><b>'
            + html.escape(message)
            + '</b></span>')
        label.set_use_markup(True)
        label.set_max_width_chars(40)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0)
        margin = 10
        label.set_margin_start(margin)
        label.set_margin_end(margin)
        label.set_margin_top(margin)
        label.set_margin_bottom(margin)
        box.add(label)
        confirm_question.show_all()
        response = confirm_question.run()
        confirm_question.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        return response

    def check_instance(self):
        '''
        Check whether another instance of the setup tool is running already
        '''
        if (dbus.SessionBus().request_name("org.ibus.typingbooster")
                != dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER):
            self.__run_message_dialog(
                _("Another instance of this app is already running."),
                Gtk.MessageType.ERROR)
            sys.exit(1)
        else:
            return False

    def on_delete_event(self, *_args):
        '''
        The window has been deleted, probably by the window manager.
        '''
        Gtk.main_quit()

    def on_destroy_event(self, *_args):
        '''
        The window has been destroyed.
        '''
        Gtk.main_quit()

    def on_close_clicked(self, *_args):
        '''
        The button to close the dialog has been clicked.
        '''
        Gtk.main_quit()

    def on_gsettings_value_changed(self, _settings, key):
        '''
        Called when a value in the settings has been changed.

        :param settings: The settings object
        :type settings: Gio.Settings object
        :param key: The key of the setting which has changed
        :type key: String
        '''
        value = itb_util.variant_to_value(self._gsettings.get_value(key))
        sys.stderr.write('Settings changed: key=%s value=%s\n' %(key, value))

        if key == 'qtimmoduleworkaround':
            self.set_qt_im_module_workaround(value, update_gsettings=False)
            return
        if key == 'addspaceoncommit':
            self.set_add_space_on_commit(value, update_gsettings=False)
            return
        if key == 'arrowkeysreopenpreedit':
            self.set_arrow_keys_reopen_preedit(value, update_gsettings=False)
            return
        if key == 'emojipredictions':
            self.set_emoji_prediction_mode(value, update_gsettings=False)
            return
        if key == 'offtherecord':
            self.set_off_the_record_mode(value, update_gsettings=False)
            return
        if key == 'autocommitcharacters':
            self.set_auto_commit_characters(value, update_gsettings=False)
            return
        if key == 'googleapplicationcredentials':
            self.set_google_application_credentials(value, update_gsettings=False)
            return
        if key == 'tabenable':
            self.set_tab_enable(value, update_gsettings=False)
            return
        if key == 'inlinecompletion':
            self.set_inline_completion(value, update_gsettings=False)
            return
        if key == 'rememberlastusedpreeditime':
            self.set_remember_last_used_preedit_ime(
                value, update_gsettings=False)
            return
        if key == 'pagesize':
            self.set_page_size(value, update_gsettings=False)
            return
        if key == 'lookuptableorientation':
            self.set_lookup_table_orientation(value, update_gsettings=False)
            return
        if key == 'preeditunderline':
            self.set_preedit_underline(value, update_gsettings=False)
            return
        if key == 'preeditstyleonlywhenlookup':
            self.set_preedit_style_only_when_lookup(
                value, update_gsettings=False)
            return
        if key == 'mincharcomplete':
            self.set_min_char_complete(value, update_gsettings=False)
            return
        if key == 'debuglevel':
            self.set_debug_level(value, update_gsettings=False)
            return
        if key == 'shownumberofcandidates':
            self.set_show_number_of_candidates(value, update_gsettings=False)
            return
        if key == 'showstatusinfoinaux':
            self.set_show_status_info_in_auxiliary_text(
                value, update_gsettings=False)
            return
        if key == 'autoselectcandidate':
            self.set_auto_select_candidate(value, update_gsettings=False)
            return
        if key == 'colorinlinecompletion':
            self.set_color_inline_completion(
                value, update_gsettings=False)
            return
        if key == 'colorinlinecompletionstring':
            self.set_color_inline_completion_string(
                value, update_gsettings=False)
            return
        if key == 'coloruserdb':
            self.set_color_userdb(
                value, update_gsettings=False)
            return
        if key == 'coloruserdbstring':
            self.set_color_userdb_string(
                value, update_gsettings=False)
            return
        if key == 'colorspellcheck':
            self.set_color_spellcheck(
                value, update_gsettings=False)
            return
        if key == 'colorspellcheckstring':
            self.set_color_spellcheck_string(
                value, update_gsettings=False)
            return
        if key == 'colordictionary':
            self.set_color_dictionary(
                value, update_gsettings=False)
            return
        if key == 'colordictionarystring':
            self.set_color_dictionary_string(
                value, update_gsettings=False)
            return
        if key == 'labeluserdb':
            self.set_label_userdb(value, update_gsettings=False)
            return
        if key == 'labeluserdbstring':
            self.set_label_userdb_string(value, update_gsettings=False)
            return
        if key == 'labelspellcheck':
            self.set_label_spellcheck(value, update_gsettings=False)
            return
        if key == 'labelspellcheckstring':
            self.set_label_spellcheck_string(value, update_gsettings=False)
            return
        if key == 'labeldictionary':
            self.set_label_dictionary(value, update_gsettings=False)
            return
        if key == 'labeldictionarystring':
            self.set_label_dictionary_string(value, update_gsettings=False)
            return
        if key == 'labelbusy':
            self.set_label_busy(value, update_gsettings=False)
            return
        if key == 'labelbusystring':
            self.set_label_busy_string(value, update_gsettings=False)
            return
        if key == 'inputmethod':
            self.set_current_imes(
                [x.strip() for x in value.split(',')], update_gsettings=False)
            return
        if key == 'dictionary':
            self.set_dictionary_names(
                [x.strip() for x in value.split(',')], update_gsettings=False)
            return
        if key == 'keybindings':
            self.set_keybindings(value, update_gsettings=False)
            return
        if key == 'dictionaryinstalltimestamp':
            # A dictionary has been updated or installed,
            # the ibus-typing-booster will (re)load all dictionaries,
            # but here in the setup tool there is nothing to do.
            sys.stderr.write('A dictionary has been updated or installed.')
            return
        sys.stderr.write('Unknown key\n')
        return

    def on_about_button_clicked(self, _button):
        '''
        The “About” button has been clicked

        :param _button: The “About” button
        :type _button: Gtk.Button object
        '''
        itb_util.ItbAboutDialog()

    def on_color_inline_completion_checkbutton(self, widget):
        '''
        The checkbutton whether to use color for inline completion
        has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_color_inline_completion(
            widget.get_active(), update_gsettings=True)

    def on_color_inline_completion_color_set(self, widget):
        '''
        A color has been set for the inline completion

        :param widget: The color button where a color was set
        :type widget: Gtk.ColorButton
        '''
        self.set_color_inline_completion_string(
            widget.get_rgba().to_string(), update_gsettings=True)

    def on_color_userdb_checkbutton(self, widget):
        '''
        The checkbutton whether to use color for candidates from the user
        database has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton

        '''
        self.set_color_userdb(widget.get_active(), update_gsettings=True)

    def on_color_userdb_color_set(self, widget):
        '''
        A color has been set for the candidates from the user database.

        :param widget: The color button where a color was set
        :type widget: Gtk.ColorButton
        '''
        self.set_color_userdb_string(
            widget.get_rgba().to_string(), update_gsettings=True)

    def on_color_spellcheck_checkbutton(self, widget):
        '''
        The checkbutton whether to use color for candidates from spellchecking
        has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_color_spellcheck(widget.get_active(), update_gsettings=True)

    def on_color_spellcheck_color_set(self, widget):
        '''
        A color has been set for the candidates from spellchecking

        :param widget: The color button where a color was set
        :type widget: Gtk.ColorButton
        '''
        self.set_color_spellcheck_string(
            widget.get_rgba().to_string(), update_gsettings=True)

    def on_color_dictionary_checkbutton(self, widget):
        '''
        The checkbutton whether to use color for candidates from a dictionary
        has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_color_dictionary(widget.get_active(), update_gsettings=True)

    def on_color_dictionary_color_set(self, widget):
        '''
        A color has been set for the candidates from a dictionary

        :param widget: The color button where a color was set
        :type widget: Gtk.ColorButton
        '''
        self.set_color_dictionary_string(
            widget.get_rgba().to_string(), update_gsettings=True)

    def on_label_userdb_checkbutton(self, widget):
        '''
        The checkbutton whether to use a label for candidates from the
        user database has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_label_userdb(widget.get_active(), update_gsettings=True)

    def on_label_userdb_entry(self, widget, _property_spec):
        '''
        The label for candidates from the user database has been changed.
        '''
        self.set_label_userdb_string(
            widget.get_text(), update_gsettings=True)

    def on_label_spellcheck_checkbutton(self, widget):
        '''
        The checkbutton whether to use a label for candidates from
        spellchecking has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_label_spellcheck(widget.get_active(), update_gsettings=True)

    def on_label_spellcheck_entry(self, widget, _property_spec):
        '''
        The label for candidates from spellchecking has been changed.
        '''
        self.set_label_spellcheck_string(
            widget.get_text(), update_gsettings=True)

    def on_label_dictionary_checkbutton(self, widget):
        '''
        The checkbutton whether to use a label for candidates from a dictionary
        has been clicked.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_label_dictionary(widget.get_active(), update_gsettings=True)

    def on_label_dictionary_entry(self, widget, _property_spec):
        '''
        The label for candidates from a dictionary has been changed.
        '''
        self.set_label_dictionary_string(
            widget.get_text(), update_gsettings=True)

    def on_label_busy_checkbutton(self, widget):
        '''
        The checkbutton whether to use a label to indicate when
        ibus-typing-booster is busy.

        :param widget: The check button clicked
        :type widget: Gtk.CheckButton
        '''
        self.set_label_busy(widget.get_active(), update_gsettings=True)

    def on_label_busy_entry(self, widget, _property_spec):
        '''
        The label to indicate when ibus-typing-booster is busy
        '''
        self.set_label_busy_string(
            widget.get_text(), update_gsettings=True)

    def on_tab_enable_checkbutton(self, widget):
        '''
        The checkbutton whether to show candidates only when
        requested with the tab key or not has been clicked.
        '''
        self.set_tab_enable(
            widget.get_active(), update_gsettings=True)

    def on_inline_completion_checkbutton(self, widget):
        '''
        The checkbutton whether to show a completion first inline in the
        preëdit instead of using a combobox to show a candidate list.
        '''
        self.set_inline_completion(
            widget.get_active(), update_gsettings=True)

    def on_show_number_of_candidates_checkbutton(self, widget):
        '''
        The checkbutton whether to show the number of candidates
        on top of the lookup table has been clicked.
        '''
        self.set_show_number_of_candidates(
            widget.get_active(), update_gsettings=True)

    def on_show_status_info_in_auxiliary_text_checkbutton(self, widget):
        '''
        The checkbutton whether to show status in the auxiliary text,
        has been clicked.
        '''
        self.set_show_status_info_in_auxiliary_text(
            widget.get_active(), update_gsettings=True)

    def on_preedit_style_only_when_lookup_checkbutton(self, widget):
        '''
        The checkbutton whether to style the preedit only when
        lookup is enabled has been clicked.
        '''
        self.set_preedit_style_only_when_lookup(
            widget.get_active(), update_gsettings=True)

    def on_auto_select_candidate_checkbutton(self, widget):
        '''
        The checkbutton whether to automatically select the best candidate
        has been clicked.
        '''
        self.set_auto_select_candidate(
            widget.get_active(), update_gsettings=True)

    def on_add_space_on_commit_checkbutton(self, widget):
        '''
        The checkbutton whether to add a space when committing by
        label or mouse click.
        '''
        self.set_add_space_on_commit(
            widget.get_active(), update_gsettings=True)

    def on_remember_last_used_preedit_ime_checkbutton(self, widget):
        '''
        The checkbutton whether to remember the last used input method
        for the preëdit has been clicked.
        '''
        self.set_remember_last_used_preedit_ime(
            widget.get_active(), update_gsettings=True)

    def on_emoji_predictions_checkbutton(self, widget):
        '''
        The checkbutton whether to predict emoji as well or not
        has been clicked.
        '''
        self.set_emoji_prediction_mode(
            widget.get_active(), update_gsettings=True)

    def on_off_the_record_checkbutton(self, widget):
        '''
        The checkbutton whether to use “Off the record” mode, i.e. whether to
        learn from user data by saving user input to the user database
        or not, has been clicked.
        '''
        self.set_off_the_record_mode(
            widget.get_active(), update_gsettings=True)

    def on_qt_im_module_workaround_checkbutton(self, widget):
        '''
        The checkbutton whether to use the workaround for the broken
        implementation of forward_key_event() in the Qt 4/5 input
        module, has been clicked.
        '''
        self.set_qt_im_module_workaround(
            widget.get_active(), update_gsettings=True)

    def on_arrow_keys_reopen_preedit_checkbutton(self, widget):
        '''
        The checkbutton whether arrow keys are allowed to reopen
        a preëdit, has been clicked.
        '''
        self.set_arrow_keys_reopen_preedit(
            widget.get_active(), update_gsettings=True)

    def on_auto_commit_characters_entry(self, widget, _property_spec):
        '''
        The list of characters triggering an auto commit has been changed.
        '''
        self.set_auto_commit_characters(
            widget.get_text(), update_gsettings=True)

    def on_google_application_credentials_button(self, _widget):
        '''
        The button to select the full path of the Google application
        credentials .json file has been clicked.
        '''
        self._google_application_credentials_button.set_sensitive(False)
        filename = ''
        chooser = Gtk.FileChooserDialog(
            title=_('Set “Google application credentials” .json file:'),
            parent=self,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_button(_('_Cancel'), Gtk.ResponseType.CANCEL)
        chooser.add_button(_('_OK'), Gtk.ResponseType.OK)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            filename = chooser.get_filename()
        chooser.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        if filename:
            self._google_application_credentials_button_label.set_text(filename)
            self.set_google_application_credentials(
                filename, update_gsettings=True)
        self._google_application_credentials_button.set_sensitive(True)

    def on_page_size_adjustment_value_changed(self, _widget):
        '''
        The page size of the lookup table has been changed.
        '''
        self.set_page_size(
            self._page_size_adjustment.get_value(), update_gsettings=True)

    def on_lookup_table_orientation_combobox_changed(self, widget):
        '''
        A change of the lookup table orientation has been requested
        with the combobox
        '''
        tree_iter = widget.get_active_iter()
        if tree_iter is not None:
            model = widget.get_model()
            orientation = model[tree_iter][1]
            self.set_lookup_table_orientation(
                orientation, update_gsettings=True)

    def on_preedit_underline_combobox_changed(self, widget):
        '''
        A change of the preedit underline style has been requested
        with the combobox
        '''
        tree_iter = widget.get_active_iter()
        if tree_iter is not None:
            model = widget.get_model()
            underline_mode = model[tree_iter][1]
            self.set_preedit_underline(
                underline_mode, update_gsettings=True)

    def on_min_char_complete_adjustment_value_changed(self, _widget):
        '''
        The value for the mininum number of characters before
        completion is attempted has been changed.
        '''
        self.set_min_char_complete(
            self._min_char_complete_adjustment.get_value(),
            update_gsettings=True)

    def on_debug_level_adjustment_value_changed(self, _widget):
        '''
        The value for the debug level has been changed.
        '''
        self.set_debug_level(
            self._debug_level_adjustment.get_value(),
            update_gsettings=True)

    def on_dictionary_to_add_selected(self, _listbox, listbox_row):
        '''
        Signal handler for selecting a dictionary to add

        :param _listbox: The list box used to select the dictionary to add
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing a dictionary name
        :type listbox_row: Gtk.ListBoxRow object
        '''
        name = listbox_row.get_child().get_text().split(' ')[0]
        if GTK_VERSION >= (3, 22, 0):
            self._dictionaries_add_popover.popdown()
        self._dictionaries_add_popover.hide()
        if not name or name in self._dictionary_names:
            return
        self.set_dictionary_names(
            [name] + self._dictionary_names, update_gsettings=True)
        self._dictionaries_listbox_selected_dictionary_index = 0
        self._dictionaries_listbox_selected_dictionary_name = name
        self._dictionaries_listbox.select_row(
            self._dictionaries_listbox.get_row_at_index(0))

    def _fill_dictionaries_add_listbox(self, filter_text):
        '''
        Fill the listbox of dictionaries to choose from

        :param filter_text: The filter text to limit the dictionaries
                            listed. Only dictionaries which contain
                            the filter text as a substring
                            (ignoring case and spaces) are listed.
        :type filter_text: String
        '''
        for child in self._dictionaries_add_popover_scroll.get_children():
            self._dictionaries_add_popover_scroll.remove(child)
        self._dictionaries_add_listbox = Gtk.ListBox()
        self._dictionaries_add_popover_scroll.add(
            self._dictionaries_add_listbox)
        self._dictionaries_add_listbox.set_visible(True)
        self._dictionaries_add_listbox.set_vexpand(True)
        self._dictionaries_add_listbox.set_selection_mode(
            Gtk.SelectionMode.SINGLE)
        self._dictionaries_add_listbox.set_activate_on_single_click(True)
        self._dictionaries_add_listbox.connect(
            'row-selected', self.on_dictionary_to_add_selected)
        rows = []
        for name in sorted(itb_util.SUPPORTED_DICTIONARIES):
            if name in self._dictionary_names:
                continue
            filter_match = False
            filter_text = itb_util.remove_accents(filter_text.lower())
            filter_words = filter_text.split()
            if (filter_text.replace(' ', '') in name.replace(' ', '').lower()):
                filter_match = True
            if IMPORT_LANGTABLE_SUCCESSFUL:
                query_languages = [
                    locale.getlocale(category=locale.LC_MESSAGES)[0], 'en']
                for query_language in query_languages:
                    if query_language:
                        language_description = itb_util.remove_accents(
                            langtable.language_name(
                                languageId=name,
                                languageIdQuery=query_language)).lower()
                        all_words_match = True
                        for filter_word in filter_words:
                            print ('** mike filter_word %s language_description %s' %(filter_word, language_description))
                            if filter_word not in language_description:
                                print('** mike false')
                                all_words_match = False
                        if all_words_match:
                            filter_match = True
            if filter_match:
                rows.append(self._fill_dictionaries_listbox_row(name)[0])
        for row in rows:
            label = Gtk.Label()
            label.set_text(html.escape(row))
            label.set_use_markup(True)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._dictionaries_add_listbox.insert(label, -1)
        self._dictionaries_add_popover.show_all()

    def on_dictionaries_search_entry_changed(self, search_entry):
        '''
        Signal handler for changed text in the dictionaries search entry

        :param search_entry: The search entry
        :type search_entry: Gtk.SearchEntry object
        '''
        filter_text = search_entry.get_text()
        self._fill_dictionaries_add_listbox(filter_text)

    def on_dictionaries_add_button_clicked(self, *_args):
        '''
        Signal handler called when the “add” button to add another
        dictionary has been clicked.
        '''
        if len(self._dictionary_names) >= itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES:
            # Actually this should never happen because the button to add
            # a dictionary should not be sensitive if the maximum number
            # of dictionaries is already reached.
            #
            # Probably it is better not to make this message translatable
            # in order not to create extra work for the translators to
            # translate a message which should never be displayed anyway.
            self.__run_message_dialog(
                'The maximum number of dictionaries is %s.'
                %itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES,
                message_type=Gtk.MessageType.ERROR)
            return
        self._dictionaries_add_popover = Gtk.Popover()
        self._dictionaries_add_popover.set_relative_to(
            self._dictionaries_add_button)
        self._dictionaries_add_popover.set_position(Gtk.PositionType.RIGHT)
        self._dictionaries_add_popover.set_vexpand(True)
        self._dictionaries_add_popover.set_hexpand(True)
        dictionaries_add_popover_vbox = Gtk.VBox()
        margin = 12
        dictionaries_add_popover_vbox.set_margin_start(margin)
        dictionaries_add_popover_vbox.set_margin_end(margin)
        dictionaries_add_popover_vbox.set_margin_top(margin)
        dictionaries_add_popover_vbox.set_margin_bottom(margin)
        dictionaries_add_popover_vbox.set_spacing(margin)
        dictionaries_add_popover_label = Gtk.Label()
        dictionaries_add_popover_label.set_text(_('Add dictionary'))
        dictionaries_add_popover_label.set_visible(True)
        dictionaries_add_popover_label.set_halign(Gtk.Align.FILL)
        dictionaries_add_popover_vbox.pack_start(
            dictionaries_add_popover_label, False, False, 0)
        dictionaries_add_popover_search_entry = Gtk.SearchEntry()
        dictionaries_add_popover_search_entry.set_can_focus(True)
        dictionaries_add_popover_search_entry.set_visible(True)
        dictionaries_add_popover_search_entry.set_halign(Gtk.Align.FILL)
        dictionaries_add_popover_search_entry.set_hexpand(False)
        dictionaries_add_popover_search_entry.set_vexpand(False)
        dictionaries_add_popover_search_entry.connect(
            'search-changed', self.on_dictionaries_search_entry_changed)
        dictionaries_add_popover_vbox.pack_start(
            dictionaries_add_popover_search_entry, False, False, 0)
        self._dictionaries_add_popover_scroll = Gtk.ScrolledWindow()
        self._dictionaries_add_popover_scroll.set_hexpand(True)
        self._dictionaries_add_popover_scroll.set_vexpand(True)
        self._dictionaries_add_popover_scroll.set_kinetic_scrolling(False)
        self._dictionaries_add_popover_scroll.set_overlay_scrolling(True)
        self._fill_dictionaries_add_listbox('')
        dictionaries_add_popover_vbox.pack_start(
            self._dictionaries_add_popover_scroll, True, True, 0)
        self._dictionaries_add_popover.add(dictionaries_add_popover_vbox)
        if GTK_VERSION >= (3, 22, 0):
            self._dictionaries_add_popover.popup()
        self._dictionaries_add_popover.show_all()

    def on_dictionaries_remove_button_clicked(self, *_args):
        '''
        Signal handler called when the “remove” button for
        an input method has been clicked.
        '''
        index = self._dictionaries_listbox_selected_dictionary_index
        if not 0 <= index < len(self._dictionary_names):
            # This should not happen, one should not be able
            # to click the remove button in this case, just return:
            return
        self.set_dictionary_names(
            self._dictionary_names[:index]
            + self._dictionary_names[index + 1:],
            update_gsettings=True)
        self._dictionaries_listbox_selected_dictionary_index = -1
        self._dictionaries_listbox_selected_dictionary_name = ''
        self._dictionaries_listbox.unselect_all()

    def on_dictionaries_up_button_clicked(self, *_args):
        '''
        Signal handler called when the “up” button for a dictionary
        has been clicked.

        Increases the priority of the selected dictionary.
        '''
        index = self._dictionaries_listbox_selected_dictionary_index
        if not 0 < index < len(self._dictionary_names):
            # This should not happen, one should not be able
            # to click the up button in this case, just return:
            return
        self.set_dictionary_names(
            self._dictionary_names[:index - 1]
            + [self._dictionary_names[index]]
            + [self._dictionary_names[index - 1]]
            + self._dictionary_names[index + 1:],
            update_gsettings=True)
        self._dictionaries_listbox_selected_dictionary_index = index - 1
        self._dictionaries_listbox_selected_dictionary_name = (
            self._dictionary_names[index - 1])
        self._dictionaries_listbox.select_row(
            self._dictionaries_listbox.get_row_at_index(index - 1))

    def on_dictionaries_down_button_clicked(self, *_args):
        '''
        Signal handler called when the “down” button for a dictionary
        has been clicked.

        Lowers the priority of the selected dictionary.
        '''
        index = self._dictionaries_listbox_selected_dictionary_index
        if not 0 <= index < len(self._dictionary_names) - 1:
            # This should not happen, one should not be able
            # to click the down button in this case, just return:
            return
        self.set_dictionary_names(
            self._dictionary_names[:index]
            + [self._dictionary_names[index + 1]]
            + [self._dictionary_names[index]]
            + self._dictionary_names[index + 2:],
            update_gsettings=True)
        self._dictionaries_listbox_selected_dictionary_index = index + 1
        self._dictionaries_listbox_selected_dictionary_name = (
            self._dictionary_names[index + 1])
        self._dictionaries_listbox.select_row(
            self._dictionaries_listbox.get_row_at_index(index + 1))

    def on_install_missing_dictionaries(self, *_args):
        '''
        Signal handler called when the “Install missing dictionaries”
        button is clicked.

        Tries to install the appropriate dictionary packages.
        '''
        missing_dictionary_packages = set()
        for name in self._dictionary_names:
            (dic_path,
             dummy_aff_path) = itb_util.find_hunspell_dictionary(name)
            if not dic_path:
                if (itb_util.distro_id() in
                    ('opensuse',
                     'opensuse-leap',
                     'opensuse-tumbleweed',
                     'sled',
                     'sles')):
                    missing_dictionary_packages.add(
                        'myspell-' + name)
                else:
                    missing_dictionary_packages.add(
                        'hunspell-' + name.split('_')[0])
        for package in missing_dictionary_packages:
            InstallPkg(package)
        self._fill_dictionaries_listbox()
        if missing_dictionary_packages:
            # Write a timestamp to dconf to trigger the callback
            # for changed dconf values in the engine and reload
            # the dictionaries:
            self._gsettings.set_value(
                'dictionaryinstalltimestamp',
                GLib.Variant.new_string(strftime('%Y-%m-%d %H:%M:%S')))

    def on_dictionary_selected(self, _listbox, listbox_row):
        '''
        Signal handler called when a dictionary is selected

        :param _listbox: The listbox used to select dictionaries
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing the dictionary name
        :type listbox_row: Gtk.ListBoxRow object
        '''
        if listbox_row:
            self._dictionaries_listbox_selected_dictionary_name = (
                listbox_row.get_child().get_text().split(' ')[0])
            self._dictionaries_listbox_selected_dictionary_index = (
                listbox_row.get_index())
            self._dictionaries_remove_button.set_sensitive(True)
            self._dictionaries_up_button.set_sensitive(
                self._dictionaries_listbox_selected_dictionary_index > 0)
            self._dictionaries_down_button.set_sensitive(
                self._dictionaries_listbox_selected_dictionary_index
                < len(self._dictionary_names) - 1)
        else:
            # all rows have been unselected
            self._dictionaries_listbox_selected_dictionary_name = ''
            self._dictionaries_listbox_selected_dictionary_index = -1
            self._dictionaries_remove_button.set_sensitive(False)
            self._dictionaries_up_button.set_sensitive(False)
            self._dictionaries_down_button.set_sensitive(False)

    def on_input_method_to_add_selected(self, _listbox, listbox_row):
        '''
        Signal handler for selecting an input method to add

        :param _listbox: The list box used to select
                              the input method to add
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing an input method name
        :type listbox_row: Gtk.ListBoxRow object
        '''
        ime = listbox_row.get_child().get_text().split(' ')[0]
        if GTK_VERSION >= (3, 22, 0):
            self._input_methods_add_popover.popdown()
        self._input_methods_add_popover.hide()
        if not ime or ime in self._current_imes:
            return
        self.set_current_imes(
            [ime] + self._current_imes, update_gsettings=True)
        self._input_methods_listbox_selected_ime_index = 0
        self._input_methods_listbox_selected_ime_name = ime
        self._input_methods_listbox.select_row(
            self._input_methods_listbox.get_row_at_index(0))

    def _fill_input_methods_add_listbox(self, filter_text):
        '''
        Fill the listbox of input methods to choose from

        :param filter_text: The filter text to limit the input methods
                            listed. Only input methods which contain
                            the filter text as a substring
                            (ignoring case and spaces) are listed.
        :type filter_text: String
        '''
        for child in self._input_methods_add_popover_scroll.get_children():
            self._input_methods_add_popover_scroll.remove(child)
        self._input_methods_add_listbox = Gtk.ListBox()
        self._input_methods_add_popover_scroll.add(
            self._input_methods_add_listbox)
        self._input_methods_add_listbox.set_visible(True)
        self._input_methods_add_listbox.set_vexpand(True)
        self._input_methods_add_listbox.set_selection_mode(
            Gtk.SelectionMode.SINGLE)
        self._input_methods_add_listbox.set_activate_on_single_click(True)
        self._input_methods_add_listbox.connect(
            'row-selected', self.on_input_method_to_add_selected)
        rows = []
        for ime in ['NoIME'] + sorted(itb_util.M17N_INPUT_METHODS):
            if ime in self._current_imes:
                continue
            row = self._fill_input_methods_listbox_row(ime)
            if (filter_text.replace(' ', '').lower()
                    in row.replace(' ', '').lower()):
                rows.append(row)
        for row in rows:
            label = Gtk.Label()
            label.set_text(html.escape(row))
            label.set_use_markup(True)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._input_methods_add_listbox.insert(label, -1)
        self._input_methods_add_popover.show_all()

    def on_input_methods_search_entry_changed(self, search_entry):
        '''
        Signal handler for changed text in the input methods search entry

        :param search_entry: The search entry
        :type search_entry: Gtk.SearchEntry object
        '''
        filter_text = search_entry.get_text()
        self._fill_input_methods_add_listbox(filter_text)

    def on_input_methods_add_button_clicked(self, *_args):
        '''
        Signal handler called when the “add” button to add another
        input method has been clicked.
        '''
        if len(self._current_imes) >= itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS:
            # Actually this should never happen because the button to add
            # an input method should not be sensitive if the maximum number
            # of input methods is  already reached.
            #
            # Probably it is better not to make this message translatable
            # in order not to create extra work for the translators to
            # translate a message which should never be displayed anyway.
            self.__run_message_dialog(
                'The maximum number of input methods is %s.'
                %itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS,
                message_type=Gtk.MessageType.ERROR)
            return
        self._input_methods_add_popover = Gtk.Popover()
        self._input_methods_add_popover.set_relative_to(
            self._input_methods_add_button)
        self._input_methods_add_popover.set_position(Gtk.PositionType.RIGHT)
        self._input_methods_add_popover.set_vexpand(True)
        self._input_methods_add_popover.set_hexpand(True)
        input_methods_add_popover_vbox = Gtk.VBox()
        margin = 12
        input_methods_add_popover_vbox.set_margin_start(margin)
        input_methods_add_popover_vbox.set_margin_end(margin)
        input_methods_add_popover_vbox.set_margin_top(margin)
        input_methods_add_popover_vbox.set_margin_bottom(margin)
        input_methods_add_popover_vbox.set_spacing(margin)
        input_methods_add_popover_label = Gtk.Label()
        input_methods_add_popover_label.set_text(_('Add input method'))
        input_methods_add_popover_label.set_visible(True)
        input_methods_add_popover_label.set_halign(Gtk.Align.FILL)
        input_methods_add_popover_vbox.pack_start(
            input_methods_add_popover_label, False, False, 0)
        input_methods_add_popover_search_entry = Gtk.SearchEntry()
        input_methods_add_popover_search_entry.set_can_focus(True)
        input_methods_add_popover_search_entry.set_visible(True)
        input_methods_add_popover_search_entry.set_halign(Gtk.Align.FILL)
        input_methods_add_popover_search_entry.set_hexpand(False)
        input_methods_add_popover_search_entry.set_vexpand(False)
        input_methods_add_popover_search_entry.connect(
            'search-changed', self.on_input_methods_search_entry_changed)
        input_methods_add_popover_vbox.pack_start(
            input_methods_add_popover_search_entry, False, False, 0)
        self._input_methods_add_popover_scroll = Gtk.ScrolledWindow()
        self._input_methods_add_popover_scroll.set_hexpand(True)
        self._input_methods_add_popover_scroll.set_vexpand(True)
        self._input_methods_add_popover_scroll.set_kinetic_scrolling(False)
        self._input_methods_add_popover_scroll.set_overlay_scrolling(True)
        self._fill_input_methods_add_listbox('')
        input_methods_add_popover_vbox.pack_start(
            self._input_methods_add_popover_scroll, True, True, 0)
        self._input_methods_add_popover.add(input_methods_add_popover_vbox)
        if GTK_VERSION >= (3, 22, 0):
            self._input_methods_add_popover.popup()
        self._input_methods_add_popover.show_all()

    def on_input_methods_remove_button_clicked(self, *_args):
        '''
        Signal handler called when the “remove” button for
        an input method has been clicked.
        '''
        index = self._input_methods_listbox_selected_ime_index
        if not 0 <= index < len(self._current_imes):
            # This should not happen, one should not be able
            # to click the remove button in this case, just return:
            return
        self.set_current_imes(
            self._current_imes[:index] + self._current_imes[index + 1:],
            update_gsettings=True)
        self._input_methods_listbox_selected_ime_index = -1
        self._input_methods_listbox_selected_ime_name = ''
        self._input_methods_listbox.unselect_all()

    def on_input_methods_up_button_clicked(self, *_args):
        '''
        Signal handler called when the “up” button for an input method
        has been clicked.

        Increases the priority of the selected input method.
        '''
        index = self._input_methods_listbox_selected_ime_index
        if not 0 < index < len(self._current_imes):
            # This should not happen, one should not be able
            # to click the up button in this case, just return:
            return
        self.set_current_imes(
            self._current_imes[:index - 1]
            + [self._current_imes[index]]
            + [self._current_imes[index - 1]]
            + self._current_imes[index + 1:],
            update_gsettings=True)
        self._input_methods_listbox_selected_ime_index = index - 1
        self._input_methods_listbox_selected_ime_name = (
            self._current_imes[index - 1])
        self._input_methods_listbox.select_row(
            self._input_methods_listbox.get_row_at_index(index - 1))

    def on_input_methods_down_button_clicked(self, *_args):
        '''
        Signal handler called when the “down” button for an input method
        has been clicked.

        Lowers the priority of the selected input method.
        '''
        index = self._input_methods_listbox_selected_ime_index
        if not 0 <= index < len(self._current_imes) - 1:
            # This should not happen, one should not be able
            # to click the down button in this case, just return:
            return
        self.set_current_imes(
            self._current_imes[:index]
            + [self._current_imes[index + 1]]
            + [self._current_imes[index]]
            + self._current_imes[index + 2:],
            update_gsettings=True)
        self._input_methods_listbox_selected_ime_index = index + 1
        self._input_methods_listbox_selected_ime_name = (
            self._current_imes[index + 1])
        self._input_methods_listbox.select_row(
            self._input_methods_listbox.get_row_at_index(index + 1))

    def on_input_methods_help_button_clicked(self, _widget):
        '''
        Show a help window for the input method selected in the
        listbox.
        '''
        if not self._input_methods_listbox_selected_ime_name:
            return
        (path,
         title,
         description,
         full_contents,
         error) = itb_util.get_ime_help(
             self._input_methods_listbox_selected_ime_name)
        window_title = self._input_methods_listbox_selected_ime_name
        if title:
            window_title += '   ' + title
        if path:
            window_title += '   ' + path
        if error:
            window_contents = error
        else:
            window_contents = description
            if full_contents:
                window_contents += (
                    '\n\n'
                    + '##############################'
                    + '##############################'
                    + '\n'
                    + 'Complete file implementing the '
                    + 'input method follows here:\n'
                    + '##############################'
                    + '##############################'
                    + '\n'
                    + full_contents)
        HelpWindow(
            parent=self,
            title=window_title,
            contents=window_contents)

    def on_input_method_selected(self, _listbox, listbox_row):
        '''
        Signal handler called when an input method is selected

        :param _listbox: The listbox used to select input methods
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing the input method name
        :type listbox_row: Gtk.ListBoxRow object
        '''
        if listbox_row:
            self._input_methods_listbox_selected_ime_name = (
                listbox_row.get_child().get_text().split(' ')[0])
            index = listbox_row.get_index()
            self._input_methods_listbox_selected_ime_index = index
            self._input_methods_remove_button.set_sensitive(True)
            self._input_methods_up_button.set_sensitive(
                0 < index < len(self._current_imes))
            self._input_methods_down_button.set_sensitive(
                0 <= index < len(self._current_imes) - 1)
            self._input_methods_help_button.set_sensitive(True)
        else:
            # all rows have been unselected
            self._input_methods_listbox_selected_ime_name = ''
            self._input_methods_listbox_selected_ime_index = -1
            self._input_methods_remove_button.set_sensitive(False)
            self._input_methods_up_button.set_sensitive(False)
            self._input_methods_down_button.set_sensitive(False)
            self._input_methods_help_button.set_sensitive(False)

    def on_shortcut_clear_clicked(self, _widget):
        '''
        The button to clear the entry fields for defining
        a custom shortcut has been clicked.
        '''
        self._shortcut_entry.set_text('')
        self._shortcut_expansion_entry.set_text('')
        self._shortcut_treeview.get_selection().unselect_all()

    def on_shortcut_delete_clicked(self, _widget):
        '''
        The button to delete a custom shortcut has been clicked.
        '''
        shortcut = self._shortcut_entry.get_text().strip()
        shortcut_expansion = (
            self._shortcut_expansion_entry.get_text().strip())
        if shortcut and shortcut_expansion:
            model = self._shortcut_treeview_model
            iterator = model.get_iter_first()
            while iterator:
                if (model.get_value(iterator, 0) == shortcut
                        and
                        model.get_value(iterator, 1) == shortcut_expansion):
                    self.tabsqlitedb.remove_phrase(
                        input_phrase=shortcut,
                        phrase=shortcut_expansion)
                    if not model.remove(iterator):
                        iterator = None
                else:
                    iterator = model.iter_next(iterator)
        self._shortcut_entry.set_text('')
        self._shortcut_expansion_entry.set_text('')
        self._shortcut_treeview.get_selection().unselect_all()

    def on_shortcut_add_clicked(self, _widget):
        '''
        The button to add a custom shortcut has been clicked.
        '''
        self._shortcut_treeview.get_selection().unselect_all()
        shortcut = self._shortcut_entry.get_text().strip()
        shortcut_expansion = (
            self._shortcut_expansion_entry.get_text().strip())
        if shortcut and shortcut_expansion:
            model = self._shortcut_treeview_model
            iterator = model.get_iter_first()
            shortcut_existing = False
            while iterator:
                if (model.get_value(iterator, 0) == shortcut
                        and
                        model.get_value(iterator, 1) == shortcut_expansion):
                    shortcut_existing = True
                iterator = model.iter_next(iterator)
            if not shortcut_existing:
                sys.stderr.write(
                    'defining shortcut: “%s” -> “%s”\n'
                    %(shortcut, shortcut_expansion))
                self.tabsqlitedb.check_phrase_and_update_frequency(
                    input_phrase=shortcut,
                    phrase=shortcut_expansion,
                    user_freq_increment=itb_util.SHORTCUT_USER_FREQ)
                model.append((shortcut, shortcut_expansion))
            self._shortcut_entry.set_text('')
            self._shortcut_expansion_entry.set_text('')
            self._shortcut_treeview.get_selection().unselect_all()

    def on_shortcut_selected(self, selection):
        '''
        A row in the list of shortcuts has been selected.
        '''
        (model, iterator) = selection.get_selected()
        if iterator:
            shortcut = model[iterator][0]
            shortcut_expansion = model[iterator][1]
            self._shortcut_entry.set_text(shortcut)
            self._shortcut_expansion_entry.set_text(shortcut_expansion)

    def on_keybindings_treeview_row_activated(
            self, _treeview, treepath, _treeviewcolumn):
        '''
        A row in the treeview listing the key bindings has been activated.

        :param treeview: The treeview listing the key bindings
        :type treeview: Gtk.TreeView object
        :param treepath: The path to the activated row
        :type treepath: Gtk.TreePath object
        :param treeviewcolumn: A column in the treeview listing the
                               key bindings
        :type treeviewcolumn: Gtk.TreeViewColumn object
        '''
        model = self._keybindings_treeview_model
        iterator = model.get_iter(treepath)
        command = model[iterator][0]
        if command != self._keybindings_selected_command:
            # This should not happen, if a row is activated it should
            # already be selected,
            # i.e. on_keybindings_treeview_row_selected() should have
            # been called already and this should have set
            # self._keybindings_selected_command
            sys.stderr.write(
                'Unexpected error, command = "%s" ' % command
                + 'self._keybindings_selected_command = "%s"\n'
                % self._keybindings_selected_command)
            return
        self._create_and_show_keybindings_edit_popover()

    def on_keybindings_treeview_row_selected(self, selection):
        '''
        A row in the treeview listing the key bindings has been selected.
        '''
        (model, iterator) = selection.get_selected()
        if iterator:
            self._keybindings_selected_command = model[iterator][0]
            self._keybindings_default_button.set_sensitive(True)
            self._keybindings_edit_button.set_sensitive(True)
        else:
            # all rows have been unselected
            self._keybindings_selected_command = ''
            self._keybindings_default_button.set_sensitive(False)
            self._keybindings_edit_button.set_sensitive(False)

    def on_keybindings_edit_listbox_row_selected(self, _listbox, listbox_row):
        '''
        Signal handler for selecting one of the key bindings
        for a certain command

        :param _listbox: The list box used to select a key binding
        :type _listbox: Gtk.ListBox object
        :param listbox_row: A row containing a key binding
        :type listbox_row: Gtk.ListBoxRow object
        '''
        if  listbox_row:
            self._keybindings_edit_popover_selected_keybinding = (
                listbox_row.get_child().get_text().split(' ')[0])
            self._keybindings_edit_popover_remove_button.set_sensitive(True)
        else:
            # all rows have been unselected
            self._keybindings_edit_popover_selected_keybinding = ''
            self._keybindings_edit_popover_remove_button.set_sensitive(False)

    def on_keybindings_edit_popover_add_button_clicked(self, *_args):
        '''
        Signal handler called when the “Add” button to add
        a key binding has been clicked.
        '''
        key_input_dialog = itb_util.ItbKeyInputDialog(parent=self)
        response = key_input_dialog.run()
        key_input_dialog.destroy()
        if response == Gtk.ResponseType.OK:
            keyval, state = key_input_dialog.e
            key = itb_util.KeyEvent(keyval, 0, state)
            keybinding = itb_util.keyevent_to_keybinding(key)
            command = self._keybindings_selected_command
            if keybinding not in self._keybindings[command]:
                self._keybindings[command].append(keybinding)
                self._fill_keybindings_edit_popover_listbox()
                self.set_keybindings(self._keybindings)

    def on_keybindings_edit_popover_remove_button_clicked(self, *_args):
        '''
        Signal handler called when the “Remove” button to remove
        a key binding has been clicked.
        '''
        keybinding = self._keybindings_edit_popover_selected_keybinding
        command = self._keybindings_selected_command
        if (keybinding and command
                and keybinding in self._keybindings[command]):
            self._keybindings[command].remove(keybinding)
            self._fill_keybindings_edit_popover_listbox()
            self.set_keybindings(self._keybindings)

    def on_keybindings_edit_popover_default_button_clicked(self, *_args):
        '''
        Signal handler called when the “Default” button to set
        the keybindings to the default has been clicked.
        '''
        default_keybindings = itb_util.variant_to_value(
            self._gsettings.get_default_value('keybindings'))
        command = self._keybindings_selected_command
        if command and command in default_keybindings:
            new_keybindings = self._keybindings
            new_keybindings[command] = default_keybindings[command]
            self._fill_keybindings_edit_popover_listbox()
            self.set_keybindings(new_keybindings)

    def _fill_keybindings_edit_popover_listbox(self):
        '''
        Fill the edit listbox to with the key bindings of the currently
        selected command
        '''
        for child in self._keybindings_edit_popover_scroll.get_children():
            self._keybindings_edit_popover_scroll.remove(child)
        self._keybindings_edit_popover_listbox = Gtk.ListBox()
        self._keybindings_edit_popover_scroll.add(
            self._keybindings_edit_popover_listbox)
        self._keybindings_edit_popover_listbox.set_visible(True)
        self._keybindings_edit_popover_listbox.set_vexpand(True)
        self._keybindings_edit_popover_listbox.set_selection_mode(
            Gtk.SelectionMode.SINGLE)
        self._keybindings_edit_popover_listbox.set_activate_on_single_click(
            True)
        self._keybindings_edit_popover_listbox.connect(
            'row-selected', self.on_keybindings_edit_listbox_row_selected)
        for keybinding in sorted(
                self._keybindings[self._keybindings_selected_command]):
            label = Gtk.Label()
            label.set_text(html.escape(keybinding))
            label.set_use_markup(True)
            label.set_xalign(0)
            margin = 1
            label.set_margin_start(margin)
            label.set_margin_end(margin)
            label.set_margin_top(margin)
            label.set_margin_bottom(margin)
            self._keybindings_edit_popover_listbox.insert(label, -1)
        self._keybindings_edit_popover_remove_button.set_sensitive(False)
        self._keybindings_edit_popover_listbox.show_all()

    def _create_and_show_keybindings_edit_popover(self):
        '''
        Create and show the popover to edit the key bindings for a command
        '''
        self._keybindings_edit_popover = Gtk.Popover()
        self._keybindings_edit_popover.set_relative_to(
            self._keybindings_edit_button)
        self._keybindings_edit_popover.set_position(Gtk.PositionType.RIGHT)
        self._keybindings_edit_popover.set_vexpand(True)
        self._keybindings_edit_popover.set_hexpand(True)
        keybindings_edit_popover_vbox = Gtk.VBox()
        margin = 12
        keybindings_edit_popover_vbox.set_margin_start(margin)
        keybindings_edit_popover_vbox.set_margin_end(margin)
        keybindings_edit_popover_vbox.set_margin_top(margin)
        keybindings_edit_popover_vbox.set_margin_bottom(margin)
        keybindings_edit_popover_vbox.set_spacing(margin)
        keybindings_edit_popover_label = Gtk.Label()
        keybindings_edit_popover_label.set_text(
            _('Edit key bindings for command “%s”'
              %self._keybindings_selected_command))
        keybindings_edit_popover_label.set_visible(True)
        keybindings_edit_popover_label.set_halign(Gtk.Align.FILL)
        keybindings_edit_popover_vbox.pack_start(
            keybindings_edit_popover_label, False, False, 0)
        self._keybindings_edit_popover_scroll = Gtk.ScrolledWindow()
        self._keybindings_edit_popover_scroll.set_hexpand(True)
        self._keybindings_edit_popover_scroll.set_vexpand(True)
        self._keybindings_edit_popover_scroll.set_kinetic_scrolling(False)
        self._keybindings_edit_popover_scroll.set_overlay_scrolling(True)
        keybindings_edit_popover_vbox.pack_start(
            self._keybindings_edit_popover_scroll, True, True, 0)
        keybindings_edit_popover_button_box = Gtk.ButtonBox()
        keybindings_edit_popover_button_box.set_can_focus(False)
        keybindings_edit_popover_button_box.set_layout(
            Gtk.ButtonBoxStyle.START)
        keybindings_edit_popover_vbox.pack_start(
            keybindings_edit_popover_button_box, False, False, 0)
        self._keybindings_edit_popover_add_button = Gtk.Button()
        keybindings_edit_popover_add_button_label = Gtk.Label()
        keybindings_edit_popover_add_button_label.set_text(
            '<span size="xx-large"><b>+</b></span>')
        keybindings_edit_popover_add_button_label.set_use_markup(True)
        self._keybindings_edit_popover_add_button.add(
            keybindings_edit_popover_add_button_label)
        self._keybindings_edit_popover_add_button.set_tooltip_text(
            _('Add a key binding'))
        self._keybindings_edit_popover_add_button.connect(
            'clicked', self.on_keybindings_edit_popover_add_button_clicked)
        self._keybindings_edit_popover_add_button.set_sensitive(True)
        self._keybindings_edit_popover_remove_button = Gtk.Button()
        keybindings_edit_popover_remove_button_label = Gtk.Label()
        keybindings_edit_popover_remove_button_label.set_text(
            '<span size="xx-large"><b>-</b></span>')
        keybindings_edit_popover_remove_button_label.set_use_markup(True)
        self._keybindings_edit_popover_remove_button.add(
            keybindings_edit_popover_remove_button_label)
        self._keybindings_edit_popover_remove_button.set_tooltip_text(
            _('Remove selected key binding'))
        self._keybindings_edit_popover_remove_button.connect(
            'clicked', self.on_keybindings_edit_popover_remove_button_clicked)
        self._keybindings_edit_popover_remove_button.set_sensitive(False)
        self._keybindings_edit_popover_default_button = Gtk.Button()
        keybindings_edit_popover_default_button_label = Gtk.Label()
        keybindings_edit_popover_default_button_label.set_text(
            _('Set to default'))
        keybindings_edit_popover_default_button_label.set_use_markup(True)
        self._keybindings_edit_popover_default_button.add(
            keybindings_edit_popover_default_button_label)
        self._keybindings_edit_popover_default_button.set_tooltip_text(
            _('Set default key bindings for the selected command'))
        self._keybindings_edit_popover_default_button.connect(
            'clicked', self.on_keybindings_edit_popover_default_button_clicked)
        self._keybindings_edit_popover_default_button.set_sensitive(True)
        keybindings_edit_popover_button_box.add(
            self._keybindings_edit_popover_add_button)
        keybindings_edit_popover_button_box.add(
            self._keybindings_edit_popover_remove_button)
        keybindings_edit_popover_button_box.add(
            self._keybindings_edit_popover_default_button)
        self._keybindings_edit_popover.add(keybindings_edit_popover_vbox)
        self._fill_keybindings_edit_popover_listbox()
        if GTK_VERSION >= (3, 22, 0):
            self._keybindings_edit_popover.popup()
        self._keybindings_edit_popover.show_all()

    def on_keybindings_edit_button_clicked(self, *_args):
        '''
        Signal handler called when the “edit” button to edit the
        key bindings for a command has been clicked.
        '''
        self._create_and_show_keybindings_edit_popover()

    def on_keybindings_default_button_clicked(self, *_args):
        '''
        Signal handler called when the “Set to default” button to reset the
        key bindings for a command to the default has been clicked.
        '''
        default_keybindings = itb_util.variant_to_value(
            self._gsettings.get_default_value('keybindings'))
        command = self._keybindings_selected_command
        if command and command in default_keybindings:
            new_keybindings = self._keybindings
            new_keybindings[command] = default_keybindings[command]
            self.set_keybindings(new_keybindings)

    def on_keybindings_all_default_button_clicked(self, *_args):
        '''
        Signal handler called when the “Set all to default” button to reset the
        all key bindings top their defaults has been clicked.
        '''
        self._keybindings_all_default_button.set_sensitive(False)
        response = self._run_are_you_sure_dialog(
            # Translators: This is the text in the centre of a small
            # dialog window, trying to confirm whether the user is
            # really sure to reset the key bindings for *all* commands
            # to their defaults. This cannot be reversed so the user
            # should be really sure he wants to do that.
            _('Do you really want to set the key bindings for '
              + 'all commands to their defaults?'))
        if response == Gtk.ResponseType.OK:
            default_keybindings = itb_util.variant_to_value(
                self._gsettings.get_default_value('keybindings'))
            self.set_keybindings(default_keybindings)
        self._keybindings_all_default_button.set_sensitive(True)

    def on_learn_from_file_clicked(self, _widget):
        '''
        The button to learn from a user supplied text file
        has been clicked.
        '''
        self._learn_from_file_button.set_sensitive(False)
        filename = ''
        chooser = Gtk.FileChooserDialog(
            title=_('Open File ...'),
            parent=self,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_button(_('_Cancel'), Gtk.ResponseType.CANCEL)
        chooser.add_button(_('_OK'), Gtk.ResponseType.OK)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            filename = chooser.get_filename()
        chooser.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration()
        if filename and os.path.isfile(filename):
            if self.tabsqlitedb.read_training_data_from_file(filename):
                dialog = Gtk.MessageDialog(
                    parent=self,
                    flags=Gtk.DialogFlags.MODAL,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    message_format=(
                        _("Learned successfully from file %(filename)s.")
                        %{'filename': filename}))
            else:
                dialog = Gtk.MessageDialog(
                    parent=self,
                    flags=Gtk.DialogFlags.MODAL,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    message_format=(
                        _("Learning from file %(filename)s failed.")
                        %{'filename': filename}))
            dialog.run()
            dialog.destroy()
        self._learn_from_file_button.set_sensitive(True)

    def on_delete_learned_data_clicked(self, _widget):
        '''
        The button requesting to delete all data learned from
        user input or text files has been clicked.
        '''
        self._delete_learned_data_button.set_sensitive(False)
        response = self._run_are_you_sure_dialog(
            # Translators: This is the text in the centre of a small
            # dialog window, trying to confirm whether the user is
            # really sure to to delete all the data
            # ibus-typing-booster has learned from what the user has
            # typed or from text files the user has given as input to
            # learn from. If the user has used ibus-typing-booster for
            # a long time, predictions are much better than in the
            # beginning because of the learning from user
            # input. Deleting this learned data cannot be reversed. So
            # the user should be really sure he really wants to do that.
            _('Do you really want to delete all language '
              + 'data learned from typing or reading files?'))
        if response == Gtk.ResponseType.OK:
            self.tabsqlitedb.remove_all_phrases()
        self._delete_learned_data_button.set_sensitive(True)

    def set_qt_im_module_workaround(self, mode, update_gsettings=True):
        '''Sets whether the workaround for the qt im module is used or not

        :param mode: Whether to use the workaround for the qt im module or not
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_qt_im_module_workaround(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._qt_im_module_workaround:
            return
        self._qt_im_module_workaround = mode
        if update_gsettings:
            self._gsettings.set_value(
                'qtimmoduleworkaround',
                GLib.Variant.new_boolean(mode))
        else:
            self._qt_im_module_workaround_checkbutton.set_active(mode)

    def set_arrow_keys_reopen_preedit(self, mode, update_gsettings=True):
        '''Sets whether the arrow keys are allowed to reopen a preëdit

        :param mode: Whether arrow keys can reopen a preëdit
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_arrow_keys_reopen_preedit(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._arrow_keys_reopen_preedit:
            return
        self._arrow_keys_reopen_preedit = mode
        if update_gsettings:
            self._gsettings.set_value(
                'arrowkeysreopenpreedit',
                GLib.Variant.new_boolean(mode))
        else:
            self._arrow_keys_reopen_preedit_checkbutton.set_active(mode)

    def set_emoji_prediction_mode(self, mode, update_gsettings=True):
        '''Sets the emoji prediction mode

        :param mode: Whether to switch emoji prediction on or off
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_emoji_prediction_mode(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._emoji_predictions:
            return
        self._emoji_predictions = mode
        if update_gsettings:
            self._gsettings.set_value(
                'emojipredictions',
                GLib.Variant.new_boolean(mode))
        else:
            self._emoji_predictions_checkbutton.set_active(mode)

    def set_off_the_record_mode(self, mode, update_gsettings=True):
        '''Sets the “Off the record” mode

        :param mode: Whether to prevent saving input to the
                     user database or not
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_off_the_record_mode(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._off_the_record:
            return
        self._off_the_record = mode
        if update_gsettings:
            self._gsettings.set_value(
                'offtherecord',
                GLib.Variant.new_boolean(mode))
        else:
            self._off_the_record_checkbutton.set_active(mode)

    def set_auto_commit_characters(self, auto_commit_characters,
                                   update_gsettings=True):
        '''Sets the auto commit characters

        :param auto_commit_characters: The characters which trigger a commit
                                       with an extra space
        :type auto_commit_characters: string
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_auto_commit_characters(%s, update_gsettings = %s)\n"
            %(auto_commit_characters, update_gsettings))
        if auto_commit_characters == self._auto_commit_characters:
            return
        self._auto_commit_characters = auto_commit_characters
        if update_gsettings:
            self._gsettings.set_value(
                'autocommitcharacters',
                GLib.Variant.new_string(auto_commit_characters))
        else:
            self._auto_commit_characters_entry.set_text(
                self._auto_commit_characters)

    def set_google_application_credentials(self, path, update_gsettings=True):
        '''Sets the auto commit characters

        :param path: Full path of the Google application credentials
                     .json file.
        :type path: string
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_google_application_credentials(%s, update_gsettings = %s)\n"
            %(path, update_gsettings))
        if path == self._google_application_credentials:
            return
        self._google_application_credentials = path
        if update_gsettings:
            self._gsettings.set_value(
                'googleapplicationcredentials',
                GLib.Variant.new_string(self._google_application_credentials))
        else:
            self._google_application_credentials_entry.set_text(
                self._google_application_credentials)

    def set_color_inline_completion(self, mode, update_gsettings=True):
        '''Sets whether to use color for inline completion

        :param mode: Whether to use color for inline completion
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_inline_completion(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._color_inline_completion:
            return
        self._color_inline_completion = mode
        self._color_inline_completion_rgba_colorbutton.set_sensitive(mode)
        if update_gsettings:
            self._gsettings.set_value(
                'colorinlinecompletion',
                GLib.Variant.new_boolean(mode))
        else:
            self._color_inline_completion_checkbutton.set_active(mode)

    def set_color_inline_completion_string(
            self, color_string, update_gsettings=True):
        '''Sets the color for inline completion

        :param color_string: The color for inline completion
        :type color_string: String
                            - Standard name from the X11 rgb.txt
                            - Hex value: “#rgb”, “#rrggbb”, “#rrrgggbbb”
                                         or ”#rrrrggggbbbb”
                            - RGB color: “rgb(r,g,b)”
                            - RGBA color: “rgba(r,g,b,a)”
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_inline_completion_string(%s, update_gsettings = %s)\n"
            %(color_string, update_gsettings))
        if color_string == self._color_inline_completion_string:
            return
        self._color_inline_completion_string = color_string
        if update_gsettings:
            self._gsettings.set_value(
                'colorinlinecompletionstring',
                GLib.Variant.new_string(color_string))
        else:
            gdk_rgba = Gdk.RGBA()
            gdk_rgba.parse(color_string)
            self._color_inline_completion_rgba_colorbutton.set_rgba(gdk_rgba)

    def set_color_userdb(self, mode, update_gsettings=True):
        '''Sets whether to use color for user database suggestions

        :param mode: Whether to use color for user database suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_userdb(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._color_userdb:
            return
        self._color_userdb = mode
        self._color_userdb_rgba_colorbutton.set_sensitive(mode)
        if update_gsettings:
            self._gsettings.set_value(
                'coloruserdb',
                GLib.Variant.new_boolean(mode))
        else:
            self._color_userdb_checkbutton.set_active(mode)

    def set_color_userdb_string(self, color_string, update_gsettings=True):
        '''Sets the color for user database suggestions

        :param color_string: The color for user database suggestions
        :type color_string: String
                            - Standard name from the X11 rgb.txt
                            - Hex value: “#rgb”, “#rrggbb”, “#rrrgggbbb”
                                         or ”#rrrrggggbbbb”
                            - RGB color: “rgb(r,g,b)”
                            - RGBA color: “rgba(r,g,b,a)”
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_userdb_string(%s, update_gsettings = %s)\n"
            %(color_string, update_gsettings))
        if color_string == self._color_userdb_string:
            return
        self._color_userdb_string = color_string
        if update_gsettings:
            self._gsettings.set_value(
                'coloruserdbstring',
                GLib.Variant.new_string(color_string))
        else:
            gdk_rgba = Gdk.RGBA()
            gdk_rgba.parse(color_string)
            self._color_userdb_rgba_colorbutton.set_rgba(gdk_rgba)

    def set_color_spellcheck(self, mode, update_gsettings=True):
        '''Sets whether to use color for spellchecking suggestions

        :param mode: Whether to use color for spellchecking suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_spellcheck(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._color_spellcheck:
            return
        self._color_spellcheck = mode
        self._color_spellcheck_rgba_colorbutton.set_sensitive(mode)
        if update_gsettings:
            self._gsettings.set_value(
                'colorspellcheck',
                GLib.Variant.new_boolean(mode))
        else:
            self._color_spellcheck_checkbutton.set_active(mode)

    def set_color_spellcheck_string(self, color_string, update_gsettings=True):
        '''Sets the color for spellchecking suggestions

        :param color_string: The color for spellchecking suggestions
        :type color_string: String
                            - Standard name from the X11 rgb.txt
                            - Hex value: “#rgb”, “#rrggbb”, “#rrrgggbbb”
                                         or ”#rrrrggggbbbb”
                            - RGB color: “rgb(r,g,b)”
                            - RGBA color: “rgba(r,g,b,a)”
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_spellcheck_string(%s, update_gsettings = %s)\n"
            %(color_string, update_gsettings))
        if color_string == self._color_spellcheck_string:
            return
        self._color_spellcheck_string = color_string
        if update_gsettings:
            self._gsettings.set_value(
                'colorspellcheckstring',
                GLib.Variant.new_string(color_string))
        else:
            gdk_rgba = Gdk.RGBA()
            gdk_rgba.parse(color_string)
            self._color_spellcheck_rgba_colorbutton.set_rgba(gdk_rgba)

    def set_color_dictionary(self, mode, update_gsettings=True):
        '''Sets whether to use color for dictionary suggestions

        :param mode: Whether to use color for dictionary suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_dictionary(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._color_dictionary:
            return
        self._color_dictionary = mode
        self._color_dictionary_rgba_colorbutton.set_sensitive(mode)
        if update_gsettings:
            self._gsettings.set_value(
                'colordictionary',
                GLib.Variant.new_boolean(mode))
        else:
            self._color_dictionary_checkbutton.set_active(mode)

    def set_color_dictionary_string(self, color_string, update_gsettings=True):
        '''Sets the color for dictionary suggestions

        :param color_string: The color for dictionary suggestions
        :type color_string: String
                            - Standard name from the X11 rgb.txt
                            - Hex value: “#rgb”, “#rrggbb”, “#rrrgggbbb”
                                         or ”#rrrrggggbbbb”
                            - RGB color: “rgb(r,g,b)”
                            - RGBA color: “rgba(r,g,b,a)”
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_color_dictionary_string(%s, update_gsettings = %s)\n"
            %(color_string, update_gsettings))
        if color_string == self._color_dictionary_string:
            return
        self._color_dictionary_string = color_string
        if update_gsettings:
            self._gsettings.set_value(
                'colordictionarystring',
                GLib.Variant.new_string(color_string))
        else:
            gdk_rgba = Gdk.RGBA()
            gdk_rgba.parse(color_string)
            self._color_dictionary_rgba_colorbutton.set_rgba(gdk_rgba)

    def set_label_userdb(self, mode, update_gsettings=True):
        '''Sets whether to use a label for user database

        :param mode: Whether to use a label for user database suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_userdb(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._label_userdb:
            return
        self._label_userdb = mode
        if update_gsettings:
            self._gsettings.set_value(
                'labeluserdb',
                GLib.Variant.new_boolean(mode))
        else:
            self._label_userdb_checkbutton.set_active(mode)

    def set_label_userdb_string(self, label_string, update_gsettings=True):
        '''Sets the label for user database suggestions

        :param label_string: The label for user database suggestions
        :type label_string: String
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_userdb_string(%s, update_gsettings = %s)\n"
            %(label_string, update_gsettings))
        if label_string == self._label_userdb_string:
            return
        self._label_userdb_string = label_string
        if update_gsettings:
            self._gsettings.set_value(
                'labeluserdbstring',
                GLib.Variant.new_string(label_string))
        else:
            self._label_userdb_entry.set_text(
                self._label_userdb_string)

    def set_label_spellcheck(self, mode, update_gsettings=True):
        '''Sets whether to use a label for spellchecking suggestions

        :param mode: Whether to use a label for spellchecking suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_spellcheck(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._label_spellcheck:
            return
        self._label_spellcheck = mode
        if update_gsettings:
            self._gsettings.set_value(
                'labelspellcheck',
                GLib.Variant.new_boolean(mode))
        else:
            self._label_spellcheck_checkbutton.set_active(mode)

    def set_label_spellcheck_string(self, label_string, update_gsettings=True):
        '''Sets the label for spellchecking suggestions

        :param label_string: The label for spellchecking suggestions
        :type label_string: String
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_spellcheck_string(%s, update_gsettings = %s)\n"
            %(label_string, update_gsettings))
        if label_string == self._label_spellcheck_string:
            return
        self._label_spellcheck_string = label_string
        if update_gsettings:
            self._gsettings.set_value(
                'labelspellcheckstring',
                GLib.Variant.new_string(label_string))
        else:
            self._label_spellcheck_entry.set_text(
                self._label_spellcheck_string)

    def set_label_dictionary(self, mode, update_gsettings=True):
        '''Sets whether to use a label for dictionary suggestions

        :param mode: Whether to use a label for dictionary suggestions
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_dictionary(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._label_dictionary:
            return
        self._label_dictionary = mode
        if update_gsettings:
            self._gsettings.set_value(
                'labeldictionary',
                GLib.Variant.new_boolean(mode))
        else:
            self._label_dictionary_checkbutton.set_active(mode)

    def set_label_dictionary_string(self, label_string, update_gsettings=True):
        '''Sets the label for dictionary suggestions

        :param label_string: The label for dictionary suggestions
        :type label_string: String
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_dictionary_string(%s, update_gsettings = %s)\n"
            %(label_string, update_gsettings))
        if label_string == self._label_dictionary_string:
            return
        self._label_dictionary_string = label_string
        if update_gsettings:
            self._gsettings.set_value(
                'labeldictionarystring',
                GLib.Variant.new_string(label_string))
        else:
            self._label_dictionary_entry.set_text(
                self._label_dictionary_string)

    def set_label_busy(self, mode, update_gsettings=True):
        '''Sets whether to use a label to indicate busy state

        :param mode: Whether to use a label to indicate busy state
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_busy(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._label_busy:
            return
        self._label_busy = mode
        if update_gsettings:
            self._gsettings.set_value(
                'labelbusy',
                GLib.Variant.new_boolean(mode))
        else:
            self._label_busy_checkbutton.set_active(mode)

    def set_label_busy_string(self, label_string, update_gsettings=True):
        '''Sets the label used to indicate busy state

        :param label_string: The label to indicate busy state
        :type label_string: String
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_label_busy_string(%s, update_gsettings = %s)\n"
            %(label_string, update_gsettings))
        if label_string == self._label_busy_string:
            return
        self._label_busy_string = label_string
        if update_gsettings:
            self._gsettings.set_value(
                'labelbusystring',
                GLib.Variant.new_string(label_string))
        else:
            self._label_busy_entry.set_text(
                self._label_busy_string)

    def set_tab_enable(self, mode, update_gsettings=True):
        '''Sets the “Tab enable” mode

        :param mode: Whether to show a candidate list only when typing Tab
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_tab_enable(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._tab_enable:
            return
        self._tab_enable = mode
        if update_gsettings:
            self._gsettings.set_value(
                'tabenable',
                GLib.Variant.new_boolean(mode))
        else:
            self._tab_enable_checkbutton.set_active(mode)

    def set_inline_completion(self, mode, update_gsettings=True):
        '''Sets the “Use inline completion” mode

        :param mode: Whether a completion is first shown inline in the preëdit
                     instead of using a combobox to show a candidate list.
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_inline_completion(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._inline_completion:
            return
        self._inline_completion = mode
        if update_gsettings:
            self._gsettings.set_value(
                'inlinecompletion',
                GLib.Variant.new_boolean(mode))
        else:
            self._inline_completion_checkbutton.set_active(mode)

    def set_remember_last_used_preedit_ime(self, mode, update_gsettings=True):
        '''Sets the “Remember last used preëdit ime” mode

        :param mode: Whether to remember the input method used last for
                     the preëdit
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_remember_last_used_preedit_ime(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._remember_last_used_preedit_ime:
            return
        self._remember_last_used_preedit_ime = mode
        if update_gsettings:
            self._gsettings.set_value(
                'rememberlastusedpreeditime',
                GLib.Variant.new_boolean(mode))
        else:
            self._remember_last_used_preedit_ime_checkbutton.set_active(mode)

    def set_page_size(self, page_size, update_gsettings=True):
        '''Sets the page size of the lookup table

        :param page_size: The page size of the lookup table
        :type mode: integer >= 1 and <= 9
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_page_size(%s, update_gsettings = %s)\n"
            %(page_size, update_gsettings))
        if page_size == self._page_size:
            return
        if 1 <= page_size <= 9:
            self._page_size = page_size
            if update_gsettings:
                self._gsettings.set_value(
                    'pagesize',
                    GLib.Variant.new_int32(page_size))
            else:
                self._page_size_adjustment.set_value(int(page_size))

    def set_lookup_table_orientation(self, orientation, update_gsettings=True):
        '''Sets the page size of the lookup table

        :param orientation: The orientation of the lookup table
        :type orientation: integer >= 0 and <= 2
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_lookup_table_orientation(%s, update_gsettings = %s)\n"
            %(orientation, update_gsettings))
        if orientation == self._lookup_table_orientation:
            return
        if 0 <= orientation <= 2:
            self._lookup_table_orientation = orientation
            if update_gsettings:
                self._gsettings.set_value(
                    'lookuptableorientation',
                    GLib.Variant.new_int32(orientation))
            else:
                for i, item in enumerate(self._lookup_table_orientation_store):
                    if self._lookup_table_orientation == item[1]:
                        self._lookup_table_orientation_combobox.set_active(i)

    def set_preedit_underline(self, underline_mode, update_gsettings=True):
        '''Sets the page size of the lookup table

        :param underline_mode: The underline mode to be used for the preedit
        :type underline_mode: integer >= 0 and <= 3
                              IBus.AttrUnderline.NONE    = 0,
                              IBus.AttrUnderline.SINGLE  = 1,
                              IBus.AttrUnderline.DOUBLE  = 2,
                              IBus.AttrUnderline.LOW     = 3,
                              IBus.AttrUnderline.ERROR   = 4,
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_preedit_underline(%s, update_gsettings = %s)\n"
            %(underline_mode, update_gsettings))
        if underline_mode == self._preedit_underline:
            return
        if 0 <= underline_mode < IBus.AttrUnderline.ERROR:
            self._preedit_underline = underline_mode
            if update_gsettings:
                self._gsettings.set_value(
                    'preeditunderline',
                    GLib.Variant.new_int32(underline_mode))
            else:
                for i, item in enumerate(self._preedit_underline_store):
                    if self._preedit_underline == item[1]:
                        self._preedit_underline_combobox.set_active(i)

    def set_min_char_complete(self, min_char_complete, update_gsettings=True):
        '''Sets the minimum number of characters to try completion

        :param min_char_complete: The minimum number of characters
                                  to type before completion is tried.
        :type min_char_complete: integer >= 1 and <= 9
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_min_char_complete(%s, update_gsettings = %s)\n"
            %(min_char_complete, update_gsettings))
        if min_char_complete == self._min_char_complete:
            return
        if 1 <= min_char_complete <= 9:
            self._min_char_complete = min_char_complete
            if update_gsettings:
                self._gsettings.set_value(
                    'mincharcomplete',
                    GLib.Variant.new_int32(min_char_complete))
            else:
                self._min_char_complete_adjustment.set_value(
                    int(min_char_complete))

    def set_debug_level(self, debug_level, update_gsettings=True):
        '''Sets the debug level

        :param debug level: The debug level
        :type debug_level: Integer >= 0 and <= 255
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_debug_level(%s, update_gsettings = %s)\n"
            %(debug_level, update_gsettings))
        if debug_level == self._debug_level:
            return
        if 0 <= debug_level <= 255:
            self._debug_level = debug_level
            if update_gsettings:
                self._gsettings.set_value(
                    'debuglevel',
                    GLib.Variant.new_int32(debug_level))
            else:
                self._debug_level.set_value(
                    int(debug_level))

    def set_show_number_of_candidates(self, mode, update_gsettings=True):
        '''Sets the “Show number of candidates” mode

        :param mode: Whether to show the number of candidates
                     in the auxiliary text
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_show_number_of_candidates(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._show_number_of_candidates:
            return
        self._show_number_of_candidates = mode
        self._show_number_of_candidates_checkbutton.set_active(mode)
        if update_gsettings:
            self._gsettings.set_value(
                'shownumberofcandidates',
                GLib.Variant.new_boolean(mode))

    def set_show_status_info_in_auxiliary_text(
            self, mode, update_gsettings=True):
        '''Sets the “Show status info in auxiliary text” mode

        :param mode: Whether to show status information in the
                     auxiliary text.
                     Currently the status information which can be
                     displayed there is whether emoji mode and
                     off-the-record mode are on or off
                     and which input method is currently used for
                     the preëdit text.
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_show_status_info_in_auxiliary_text"
            + "(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._show_status_info_in_auxiliary_text:
            return
        self._show_status_info_in_auxiliary_text = mode
        if update_gsettings:
            self._gsettings.set_value(
                'showstatusinfoinaux',
                GLib.Variant.new_boolean(mode))
        else:
            self._show_status_info_in_auxiliary_text_checkbutton.set_active(
                mode)

    def set_preedit_style_only_when_lookup(
            self, mode, update_gsettings=True):
        '''Sets the “Use preedit style only if lookup is enabled” mode

        :param mode: Whether a preedit style like underlining should
                     be enabled only when lookup is enabled.
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_preedit_style_only_when_lookup"
            + "(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._preedit_style_only_when_lookup:
            return
        self._preedit_style_only_when_lookup = mode
        if update_gsettings:
            self._gsettings.set_value(
                'preeditstyleonlywhenlookup',
                GLib.Variant.new_boolean(mode))
        else:
            self._preedit_style_only_when_lookup_checkbutton.set_active(mode)

    def set_auto_select_candidate(self, mode, update_gsettings=True):
        '''Sets the “Automatically select the best candidate” mode

        :param mode: Whether to automatically select the best candidate
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_auto_select_candidate(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._auto_select_candidate:
            return
        self._auto_select_candidate = mode
        if update_gsettings:
            self._gsettings.set_value(
                'autoselectcandidate',
                GLib.Variant.new_boolean(mode))
        else:
            self._auto_select_candidate_checkbutton.set_active(mode)

    def set_add_space_on_commit(self, mode, update_gsettings=True):
        '''Sets the “Add a space when committing by label or mouse” mode

        :param mode: Whether to add a space when committing by label or mouse
        :type mode: boolean
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        sys.stderr.write(
            "set_add_space_on_commit(%s, update_gsettings = %s)\n"
            %(mode, update_gsettings))
        if mode == self._add_space_on_commit:
            return
        self._add_space_on_commit = mode
        if update_gsettings:
            self._gsettings.set_value(
                'addspaceoncommit',
                GLib.Variant.new_boolean(mode))
        else:
            self._add_space_on_commit_checkbutton.set_active(mode)

    def set_current_imes(self, imes, update_gsettings=True):
        '''Set current list of input methods

        :param imes: List of input methods
        :type imes: List of strings
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        imes = [re.sub(re.escape('noime'), 'NoIME', x.strip(),
                       flags=re.IGNORECASE)
                for x in imes if x]
        if imes == self._current_imes: # nothing to do
            return
        if len(imes) > itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS:
            sys.stderr.write(
                'Trying to set more than the allowed maximum of %s '
                %itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS
                + 'input methods.\n'
                + 'Trying to set: %s\n' %imes
                + 'Really setting: %s\n'
                %imes[:itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS])
            imes = imes[:itb_util.MAXIMUM_NUMBER_OF_INPUT_METHODS]
        self._current_imes = imes
        self._fill_input_methods_listbox()
        if update_gsettings:
            self._gsettings.set_value(
                'inputmethod',
                GLib.Variant.new_string(','.join(imes)))
        else:
            # unselect all rows:
            self._input_methods_listbox_selected_ime_name = ''
            self._input_methods_listbox_selected_ime_index = -1
            self._input_methods_remove_button.set_sensitive(False)
            self._input_methods_up_button.set_sensitive(False)
            self._input_methods_down_button.set_sensitive(False)
            self._input_methods_help_button.set_sensitive(False)


    def set_dictionary_names(self, dictionary_names, update_gsettings=True):
        '''Set current dictionary names

        :param dictionary_names: List of names of dictionaries to use
        :type dictionary_names: List of strings
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        dictionary_names = [x for x in dictionary_names if x]
        if dictionary_names == self._dictionary_names: # nothing to do
            return
        if len(dictionary_names) > itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES:
            sys.stderr.write(
                'Trying to set more than the allowed maximum of %s '
                %itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES
                + 'dictionaries.\n'
                + 'Trying to set: %s\n' %dictionary_names
                + 'Really setting: %s\n'
                %dictionary_names[:itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES])
            dictionary_names = dictionary_names[:itb_util.MAXIMUM_NUMBER_OF_DICTIONARIES]
        self._dictionary_names = dictionary_names
        self._fill_dictionaries_listbox()
        if update_gsettings:
            self._gsettings.set_value(
                'dictionary',
                GLib.Variant.new_string(','.join(dictionary_names)))
        else:
            # unselect all rows:
            self._dictionaries_listbox_selected_dictionary_name = ''
            self._dictionaries_listbox_selected_dictionary_index = -1
            self._dictionaries_remove_button.set_sensitive(False)
            self._dictionaries_up_button.set_sensitive(False)
            self._dictionaries_down_button.set_sensitive(False)

    def set_keybindings(self, keybindings, update_gsettings=True):
        '''Set current key bindings

        :param keybindings: The key bindings to use
        :type keybindings: Dictionary of key bindings for commands.
                           Commands which do not already
                           exist in the current key bindings dictionary
                           will be ignored.
        :param update_gsettings: Whether to write the change to Gsettings.
                                 Set this to False if this method is
                                 called because the Gsettings key changed
                                 to avoid endless loops when the Gsettings
                                 key is changed twice in a short time.
        :type update_gsettings: boolean
        '''
        new_keybindings = {}
        # Get the default settings:
        new_keybindings = itb_util.variant_to_value(
            self._gsettings.get_default_value('keybindings'))
        # Update the default settings with the possibly changed settings:
        itb_util.dict_update_existing_keys(new_keybindings, keybindings)
        self._keybindings = new_keybindings
        # update the tree model
        model = self._keybindings_treeview_model
        iterator = model.get_iter_first()
        while iterator:
            for command in self._keybindings:
                if model.get_value(iterator, 0) == command:
                    model.set_value(iterator, 1,
                                    repr(self._keybindings[command]))
            iterator = model.iter_next(iterator)
        if update_gsettings:
            variant_dict = GLib.VariantDict(GLib.Variant('a{sv}', {}))
            for command in sorted(self._keybindings):
                variant_array = GLib.Variant.new_array(
                    GLib.VariantType('s'),
                    [GLib.Variant.new_string(x)
                     for x in self._keybindings[command]])
                variant_dict.insert_value(command, variant_array)
            self._gsettings.set_value(
                'keybindings',
                variant_dict.end())

class HelpWindow(Gtk.Window):
    '''
    A window to show help

    :param parent: The parent object
    :type parent: Gtk.Window object
    :param title: Title of the help window
    :type title: String
    :param contents: Contents of the help window
    :type contents: String
    '''
    def __init__(self,
                 parent=None,
                 title='',
                 contents=''):
        Gtk.Window.__init__(self, title=title)
        if parent:
            self.set_parent(parent)
            self.set_transient_for(parent)
            # to receive mouse events for scrolling and for the close
            # button
            self.set_modal(True)
        self.set_destroy_with_parent(False)
        self.set_default_size(600, 500)
        self.vbox = Gtk.VBox(spacing=0)
        self.add(self.vbox)
        self.text_buffer = Gtk.TextBuffer()
        self.text_buffer.insert_at_cursor(contents)
        self.text_view = Gtk.TextView()
        self.text_view.set_buffer(self.text_buffer)
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_justification(Gtk.Justification.LEFT)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.scrolledwindow = Gtk.ScrolledWindow()
        self.scrolledwindow.set_hexpand(True)
        self.scrolledwindow.set_vexpand(True)
        self.scrolledwindow.add(self.text_view)
        self.vbox.pack_start(self.scrolledwindow, True, True, 0)
        self.close_button = Gtk.Button()
        self.close_button_label = Gtk.Label()
        self.close_button_label.set_text_with_mnemonic(_('_Close'))
        self.close_button.add(self.close_button_label)
        self.close_button.connect("clicked", self.on_close_button_clicked)
        self.hbox = Gtk.HBox(spacing=0)
        self.hbox.pack_end(self.close_button, False, False, 0)
        self.vbox.pack_start(self.hbox, False, False, 5)
        self.show_all()

    def on_close_button_clicked(self, _widget):
        '''
        Close the input method help window when the close button is clicked
        '''
        self.destroy()

if __name__ == '__main__':
    if not _ARGS.no_debug:
        if (not os.access(
                os.path.expanduser('~/.local/share/ibus-typing-booster'),
                os.F_OK)):
            os.system('mkdir -p ~/.local/share/ibus-typing-booster')
        LOGFILE = os.path.expanduser(
            '~/.local/share/ibus-typing-booster/setup-debug.log')
        sys.stdout = open(LOGFILE, mode='a', buffering=1)
        sys.stderr = open(LOGFILE, mode='a', buffering=1)
        print('--- %s ---' %strftime('%Y-%m-%d: %H:%M:%S'))

    # Workaround for
    # https://bugzilla.gnome.org/show_bug.cgi?id=622084
    # Bug 622084 - Ctrl+C does not exit gtk app
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        sys.stderr.write("IBUS-WARNING **: Using the fallback 'C' locale")
        locale.setlocale(locale.LC_ALL, 'C')
    i18n_init()
    if IBus.get_address() is None:
        DIALOG = Gtk.MessageDialog(
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format=_('ibus is not running.'))
        DIALOG.run()
        DIALOG.destroy()
        sys.exit(1)
    SETUP_UI = SetupUI()
    Gtk.main()
