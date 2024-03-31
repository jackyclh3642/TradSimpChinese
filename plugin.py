#!/usr/bin/env python
# -*- coding: utf-8 -*-

__license__ = 'GPL 3'
__copyright__ = '2022, Hopkins'

import re, os.path
import css_parser
from html.parser import HTMLParser
from html.entities import name2codepoint
import sys


from opencc_python import OpenCC

'''
TradSimpChinese
This Calibre plugin converts the Chinese text characters in an ebook. It can
convert texts using traditional characters in a text containing simplified
characters. It also can convert texts using simplified characters in a text
containing traditional characters.

NOTE:
This code is based on the Calibre plugin Diap's Editing Toolbag

SEE ALSO:
https://en.wikipedia.org/wiki/Simplified_Chinese_characters
https://en.wikipedia.org/wiki/Traditional_Chinese_characters
https://en.wikipedia.org/wiki/Debate_on_traditional_and_simplified_Chinese_characters

'''

CONFIG_FILE = 'config'
DICT_FILE = 'dictionary'


# Default punctuation characters that are not enabled. Used to set the values for default button in
# the punctuation dialog. Vertical presentation forms of these are not generally used in vertical text.
# List was derived by examining actual vertical text epub books.
PUNC_OMITS = "。、；：！？…‥＿﹏，"


# Index into criteria      criteria values

INPUT_SOURCE = 0           # 0=whole book, 1=current file, 2=selected text
CONVERSION_TYPE = 1        # 0=No change, 1=trad->simp, 2=simp->trad, 3=trad->trad
INPUT_LOCALE = 2           # 0=Mainland, 1=Hong Kong, 2=Taiwan 3=Japan
OUTPUT_LOCALE = 3          # 0=Mainland, 1=Hong Kong, 2=Taiwan 3=Japan
USE_TARGET_PHRASES = 4     # True/False
QUOTATION_TYPE = 5         # 0=No change, 1=Western, 2=East Asian
OUTPUT_ORIENTATION = 6     # 0=No change, 1=Horizontal, 2=Vertical
UPDATE_PUNCTUATION = 7     # True/False
PUNC_DICT = 8              # punctuation swapping dictionary based on settings, may be None
PUNC_REGEX = 9             # precompiled regex expression to swap punctuation, may be None


#<!--PI_SELTEXT_START-->
seltext_start_tag = "PI_SELTEXT_START"

#<!--PI_SELTEXT_END-->
seltext_end_tag   = "PI_SELTEXT_END"

# Horizontal full width characters to their vertical presentation forms lookup before punctuation dialog
# modification
_h2v_master_dict = {'。':'︒', '、':'︑', '；':'︔', '：':'︓', '！':'︕', '？':'︖', '「':'﹁', '」':'﹂', '〈':'︿', '〉':'﹀',
        '『':'﹃', '』':'﹄', '《':'︽', '》':'︾', '【':'︻', '（':'︵', '】':'︼', '）':'︶','〖': '︗', '〗':'︘',
        '〔':'︹', '｛':'︷', '〕':'︺', '｝':'︸', '［':'﹇', '］':'﹈', '…':'︙', '‥':'︰', '—':'︱', '＿':'︳',
        '﹏':'︴', '，':'︐'}


from plugin_utils import Qt, QtCore, QtGui, QtWidgets, QAction
from plugin_utils import PluginApplication, iswindows, _t  # , Signal, Slot, loadUi


DEBUG = 1
if DEBUG:
    if 'PySide6' in sys.modules:
        print('Plugin using PySide6')
    else:
        print('Plugin using PyQt5')

# A function to mimic Calibre's get_resources function, take in file path and return binary content
def get_resources(path):
    absolute_path = os.path.join(os.path.dirname(__file__), path)
    assert os.path.isfile(absolute_path)
    with open(absolute_path, "rb") as f:
        data = f.read()
    return data


# Calibre function passed into converter for getting resource files
def get_resource_file(file_type, file_name):
    if file_type == CONFIG_FILE:
        return get_resources('opencc_python/config/' + file_name)
    elif file_type == DICT_FILE:
        return get_resources('opencc_python/dictionary/' + file_name)
    else:
        raise ValueError('conversion value incorrect')

class PuncuationDialog(QtWidgets.QDialog):

    def __init__(self, prefs, punc_dict, default_omitted_puncuation):
        self.prefs = prefs
        self.punc_dict = punc_dict
        self.default_omitted_puncuation = default_omitted_puncuation
        self.puncSettings = set()

        super().__init__()
        self.setWindowTitle(_t('PuncuationDialog', 'Chinese Punctuation'))
        
        self.setup_ui()

    


    def setup_ui(self):
        self.punc_setting = {}
        self.checkbox_dict = {}

        # Create layout for entire dialog
        layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(layout)

        #Create a scroll area for the top part of the dialog
        self.scrollArea = QtWidgets.QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        # Create widget for all the contents of the dialog except the buttons
        self.scrollContentWidget = QtWidgets.QWidget(self.scrollArea)
        self.scrollArea.setWidget(self.scrollContentWidget)
        widgetLayout = QtWidgets.QVBoxLayout(self.scrollContentWidget)

        # Add scrollArea to dialog
        layout.addWidget(self.scrollArea)

        self.punctuation_group_box = QtWidgets.QGroupBox(_t('PuncuationDialog', 'Punctuation'))
        widgetLayout.addWidget(self.punctuation_group_box)


        self.punctuation_group_box_layout = QtWidgets.QVBoxLayout()
        self.punctuation_group_box.setLayout(self.punctuation_group_box_layout)

        for x in self.punc_dict:
            str = x + " <-> " + self.punc_dict[x]
            widget = QtWidgets.QCheckBox(str)
            self.checkbox_dict[x] = widget
            self.punctuation_group_box_layout.addWidget(widget)
            if x in self.prefs['punc_omits']:
                widget.setChecked(False)
            else:
                widget.setChecked(True)


        self.button_box_settings = QtWidgets.QDialogButtonBox()
        self.clearall_button = self.button_box_settings.addButton("Clear All", QtWidgets.QDialogButtonBox.ActionRole)
        self.setall_button = self.button_box_settings.addButton("Set All", QtWidgets.QDialogButtonBox.ActionRole)
        self.default_button = self.button_box_settings.addButton("Default", QtWidgets.QDialogButtonBox.ActionRole)
        self.button_box_settings.clicked.connect(self._action_clicked)
        layout.addWidget(self.button_box_settings)

        self.button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self._ok_clicked)
        self.button_box.rejected.connect(self._reject_clicked)
        layout.addWidget(self.button_box)


    def savePrefs(self):
        setting = ""
        for x in self.puncSettings:
            setting = setting + x
        self.prefs['punc_omits'] = setting


    def _ok_clicked(self):
        self.puncSettings.clear()
        # Loop through and update set of unchecked items
        for x in self.checkbox_dict.keys():
            if not self.checkbox_dict[x].isChecked():
                self.puncSettings.add(x)
        self.savePrefs()
        self.accept()


    def _reject_clicked(self):
        # Restore back to values when first opened
        # This will be the same as the preferences
        ## loop through all checkboxes
        for x in self.checkbox_dict.keys():
            self.checkbox_dict[x].blockSignals(True)
            if x in self.prefs['punc_omits']:
                self.checkbox_dict[x].setChecked(False)
            else:
                self.checkbox_dict[x].setChecked(True)
            self.checkbox_dict[x].blockSignals(False)
        self.reject()


    def _action_clicked(self, button):
        ## Find out which button is pressed
        if button is self.clearall_button:
            ## loop through all checkboxes and unset
            for x in self.checkbox_dict.values():
                x.blockSignals(True)
                x.setChecked(False)
                x.blockSignals(False)

        elif button is self.setall_button:
            ## loop through all checkboxes and set
            for x in self.checkbox_dict.values():
                x.blockSignals(True)
                x.setChecked(True)
                x.blockSignals(False)

        elif button is self.default_button:
            ## loop through all checkboxes
            for x in self.checkbox_dict.keys():
                self.checkbox_dict[x].blockSignals(True)
                if x in self.default_omitted_puncuation:
                    self.checkbox_dict[x].setChecked(False)
                else:
                    self.checkbox_dict[x].setChecked(True)
                self.checkbox_dict[x].blockSignals(False)

class HTML_TextProcessor(HTMLParser):
    """
    This class takes in HTML files as a string.
    """

    def __init__(self, textConvertor = None):
          super().__init__(convert_charrefs=False)
          self.recording = 0
          self.result = []
          self.textConverter = textConvertor
          self.criteria = None
          self.converting = True
          self.language = None
          self.force_stylesheet = False

          # Create regular expressions to modify quote styles
          self.trad_to_simp_quotes = {'「':'“', '」':'”', '『':'‘', '』':'’'}
          self.trad_to_simp_re = re.compile('|'.join(map(re.escape, self.trad_to_simp_quotes)))

          self.simp_to_trad_quotes = {'“':'「', '”':'」', '‘':'『', '’':'』'}
          self.simp_to_trad_re = re.compile('|'.join(map(re.escape, self.simp_to_trad_quotes)))

          # Create regular expression to modify lang attribute
          self.zh_re = re.compile(r'lang=\"zh-\w+\"|lang=\"zh\"', re.IGNORECASE)


    # Use this if one wants to reset the converter
    def setTextConvertor(self, textConvertor):
        self.textConverter = textConvertor

    def setLanguageAttribute(self, language):
        self.language = language

    def replace_quotations(self, data):
        # update quotes if desired
        if self.criteria[QUOTATION_TYPE] == 1:
            # traditional to simplified
            htmlstr_corrected = self.trad_to_simp_re.sub(lambda match: self.trad_to_simp_quotes[match.group(0)], data)
        elif self.criteria[QUOTATION_TYPE] == 2:
            # simplified to traditional
            htmlstr_corrected = self.simp_to_trad_re.sub(lambda match: self.simp_to_trad_quotes[match.group(0)], data)
        else:
            # no quote changes desired
            htmlstr_corrected = data
        return htmlstr_corrected


    # multiple_replace copied from ActiveState http://code.activestate.com/recipes/81330-single-pass-multiple-replace/
    # Copyright 2001 Xavier Defrang
    # PSF (Python Software Foundation) license (GPL Compatible)
    # https://docs.python.org/3/license.html
    def multiple_replace(self, replace_regex, replace_dict, text):
      # For each match, look-up corresponding value in dictionary
      return replace_regex.sub(lambda mo: replace_dict[mo.string[mo.start():mo.end()]], text)

    def processText(self, data, criteria):
##        print("processText:", data)
##        print('processText Criteria: ', criteria)

        self.criteria = criteria
        self.result.clear()
        self.reset()
        if self.criteria[INPUT_SOURCE] == 2:
            # turn off converting until a start comment seen
            self.converting = False
        else:
            self.converting = True

##        print("Feeding in text")
        self.feed(data)
        self.close()
        # return result
        return "".join(self.result)

    def handle_starttag(self, tag, attrs):
##        print("Literal start tag:", self.get_starttag_text())
##        print("Start tag:", tag)
##        for attr in attrs:
##            print("     attr:", attr)

        # change language code inside of tags
        if self.converting and (self.criteria[CONVERSION_TYPE] != 0) and (self.language != None):
            text = self.zh_re.sub(self.language, self.get_starttag_text())
        else:
            text = self.get_starttag_text()

        if tag == "html":
            attrs_list = [attr[0] for attr in attrs]
            if "xml:lang" not in attrs_list:
                text = text[:-1] + f' xml:{self.language}' + ">"

        self.result.append(text)


        

    def handle_endtag(self, tag):
        if tag == "head" and self.force_stylesheet:
            self.result.append('<link rel="stylesheet" type="text/css" href="./Styles/stylesheet.css"/>')
            # TODO: This assume that the OBPS/*.html and OBPS/Styles/stylesheet.css, the former is not enforced
        self.result.append("</" + tag + ">")

##        print("End tag  :", tag)

    def handle_startendtag(self, tag,  attrs):
##        print("Literal start-end tag:", self.get_starttag_text())
##        print("Strt-End tag     :", tag)
##        for attr in attrs:
##            print("     attr:", attr)

        # change language code inside of tags
        if (self.criteria[INPUT_SOURCE] == 0) and (self.criteria[CONVERSION_TYPE] != 0) and (self.language != None):
            self.result.append(self.zh_re.sub(self.language, self.get_starttag_text()))
        else:
            self.result.append(self.get_starttag_text())

    def handle_data(self, text):
##        print("Data     :", text)

        if text.isspace():
##            print("handle_data is only whitespace")
            self.result.append(text)
        else:
            if self.converting:
                if (self.criteria[OUTPUT_ORIENTATION] == 0) or (self.criteria[OUTPUT_ORIENTATION] == 2):
                    # Convert quotation marks
                    if (self.criteria[QUOTATION_TYPE] != 0):
                        text = self.replace_quotations(text)

                # Convert punctuation to vertical or horizontal using provided regular expression
                # self.criteria[PUNC_REGEX] is only set if vertical or horizontal change selected
                if self.criteria[PUNC_REGEX] != None:
                    text = self.multiple_replace(self.criteria[PUNC_REGEX], self.criteria[PUNC_DICT], text)

                if (self.criteria[OUTPUT_ORIENTATION] == 1):
                    # Convert quotation marks
                    if (self.criteria[QUOTATION_TYPE] != 0):
                        text = self.replace_quotations(text)

            # Convert text to traditional or simplified if needed
##            print('handle_data CONVERSION_TYPE criteria = ', self.criteria[CONVERSION_TYPE])
            if self.criteria[CONVERSION_TYPE] != 0 and self.converting:
##                print('handle_data calling self.textConverter.convert(text)')
                self.result.append(self.textConverter.convert(text))
            else:
##                print('handle_data NOT calling self.textConverter.convert(text)')
                self.result.append(text)


    def handle_comment(self, data):
##        print('handle_comment raw data:', data)
##        print('handle_comment stripped data:', data.strip())
##        print('seltext_start_tag:', seltext_start_tag)
##        print('seltext_end_tag:', seltext_end_tag)
##        print('handle_comment self.criteria[INPUT_SOURCE]:', self.criteria[INPUT_SOURCE])
        if (self.criteria[INPUT_SOURCE] == 2) and (data.strip() == seltext_start_tag):
            self.converting = True
##            print('handle_comment converting set to True')
        elif (self.criteria[INPUT_SOURCE] == 2) and (data.strip() == seltext_end_tag):
            self.converting = False
##            print('handle_comment converting set to False')
        self.result.append("<!--" + data + "-->")
##        print("Comment  :", data)

    def handle_pi(self, data):
        self.result.append("<?" + data + ">")
##        print("<?  :", data)

    def handle_entityref(self, name):
        self.result.append("&" + name + ";")
##        c = chr(name2codepoint[name])
##        print("Named ent:", c)
##
    def handle_charref(self, name):
        self.result.append("&#" + name + ";")
##        if name.startswith('x'):
##            c = chr(int(name[1:], 16))
##        else:
##            c = chr(int(name))
##        print("Num ent  :", c)

    def handle_decl(self, data):
        self.result.append("<!" + data + ">")
##        print("Decl     :", data)

    def unknown_decl(self, data):
        self.result.append("<!" + data + ">")
##        print("Unknown Decl     :", data)


class guiTradSimpChinese(QtWidgets.QMainWindow):
    def __init__(self, bk):
        super().__init__()

        self.converter = OpenCC(get_resource_file)

        # Create the HTML parser and pass in the converer  
        self.parser = HTML_TextProcessor(self.converter)

        # The Sigil BookContainer
        self.bk = bk

        # Initialize defaults for preferences
        self.prefs = self.bk.getPrefs()
        self.prefsPrep()

        self.force_entire_book = False

        app = PluginApplication.instance()
        self.setWindowTitle(_t('guiTradSimpChinese', 'Chinese Conversion'))
        self.punctuation_dialog = PuncuationDialog(self.prefs, _h2v_master_dict, PUNC_OMITS)

        self.setup_ui()

    def prefsPrep(self):
        # Default settings for dialog widgets

        # If this is a new installation
        if self.prefs == {}:
            self.prefs['input_source'] = 0
            self.prefs['conversion_type'] = 0
            self.prefs['input_locale'] = 0
            self.prefs['output_locale'] = 0
            self.prefs['use_target_phrases'] = True
            self.prefs['quotation_type'] = 0
            self.prefs['output_orientation'] = 0
            self.prefs['update_punctuation'] = False
            self.prefs['punc_omits'] = PUNC_OMITS
            # Write the preferences out to the JSON file
            self.bk.savePrefs(self.prefs)


        # Initialize the defaults. No need to commit since these are not
        # stored in the JSON file
        self.prefs.defaults['input_source'] = 0           # 0=whole book, 1=current file, 2=selected text

        self.prefs.defaults['conversion_type'] = 0        # 0=No change, 1=trad->simp, 2=simp->trad, 3=trad->trad
        self.prefs.defaults['input_locale'] = 0           # 0=Mainland, 1=Hong Kong, 2=Taiwan
        self.prefs.defaults['output_locale'] = 0          # 0=Mainland, 1=Hong Kong, 2=Taiwan
        self.prefs.defaults['use_target_phrases'] = True  # True/False

        self.prefs.defaults['quotation_type'] = 0         # 0=No change, 1=Western, 2=East Asian

        self.prefs.defaults['output_orientation'] = 0     # 0=No change, 1=Horizontal, 2=Vertical

        self.prefs.defaults['update_punctuation'] = False #  True/False

        self.prefs.defaults['punc_omits'] = PUNC_OMITS    # Horizontal mark string in horizontal/vertical
                                                          # dictionary pairs that is NOT to be used. No
                                                          # space between marks in string.
    
    def setup_ui(self):
        self.quote_for_trad_target = _t('guiTradSimpChinese', "Update quotes: “ ”,‘ ’ -> 「 」,『 』")
        self.quote_for_simp_target = _t('guiTradSimpChinese', "Update quotes: 「 」,『 』 -> “ ”,‘ ’")

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        
        #Create a scroll area for the top part of the dialog
        self.scrollArea = QtWidgets.QScrollArea()
        self.scrollArea.setWidgetResizable(True)

        # Create widget for all the contents of the dialog except the OK and Cancel buttons
        self.scrollContentWidget = QtWidgets.QWidget(self.scrollArea)
        self.scrollArea.setWidget(self.scrollContentWidget)
        widgetLayout = QtWidgets.QVBoxLayout(self.scrollContentWidget)

        # Add scrollArea to dialog
        layout.addWidget(self.scrollArea)

        self.operation_group_box = QtWidgets.QGroupBox(_t('guiTradSimpChinese', 'Conversion Direction'))
        widgetLayout.addWidget(self.operation_group_box)
        operation_group_box_layout = QtWidgets.QVBoxLayout()
        self.operation_group_box.setLayout(operation_group_box_layout)

        self.operation_group=QtWidgets.QButtonGroup(self)
        self.no_conversion_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'No Conversion'))
        self.operation_group.addButton(self.no_conversion_button)
        self.trad_to_simp_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Traditional to Simplified'))
        self.operation_group.addButton(self.trad_to_simp_button)
        self.simp_to_trad_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Simplified to Traditional'))
        self.operation_group.addButton(self.simp_to_trad_button)
        self.trad_to_trad_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Traditional to Traditional'))
        self.operation_group.addButton(self.trad_to_trad_button)
        operation_group_box_layout.addWidget(self.no_conversion_button)
        operation_group_box_layout.addWidget(self.trad_to_simp_button)
        operation_group_box_layout.addWidget(self.simp_to_trad_button)
        operation_group_box_layout.addWidget(self.trad_to_trad_button)
        self.operation_group.buttonClicked.connect(self.on_op_button_clicked)


        self.style_group_box = QtWidgets.QGroupBox(_t('guiTradSimpChinese', 'Language Styles'))
        widgetLayout.addWidget(self.style_group_box)
        style_group_box_layout = QtWidgets.QVBoxLayout()
        self.style_group_box.setLayout(style_group_box_layout)

        input_layout = QtWidgets.QHBoxLayout()
        style_group_box_layout.addLayout(input_layout)
        self.input_region_label = QtWidgets.QLabel(_t('guiTradSimpChinese', 'Input:'))
        input_layout.addWidget(self.input_region_label)
        self.input_combo = QtWidgets.QComboBox()
        input_layout.addWidget(self.input_combo)
        self.input_combo.addItems([_t('guiTradSimpChinese', 'Mainland'),
                                   _t('guiTradSimpChinese', 'Hong Kong'),
                                   _t('guiTradSimpChinese', 'Taiwan'),
                                   _t('guiTradSimpChinese', 'Japan')])
        self.input_combo.setToolTip(_t('guiTradSimpChinese', 'Select the origin region of the input'))
        self.input_combo.currentIndexChanged.connect(self.update_gui)

        output_layout = QtWidgets.QHBoxLayout()
        style_group_box_layout.addLayout(output_layout)
        self.output_region_label = QtWidgets.QLabel(_t('guiTradSimpChinese', 'Output:'))
        output_layout.addWidget(self.output_region_label)
        self.output_combo = QtWidgets.QComboBox()
        output_layout.addWidget(self.output_combo)
        self.output_combo.addItems([_t('guiTradSimpChinese', 'Mainland'),
                                    _t('guiTradSimpChinese', 'Hong Kong'),
                                    _t('guiTradSimpChinese', 'Taiwan'),
                                    _t('guiTradSimpChinese', 'Japan')])
        self.output_combo.setToolTip(_t('guiTradSimpChinese', 'Select the desired region of the output'))
        self.output_combo.currentIndexChanged.connect(self.update_gui)

        self.use_target_phrases = QtWidgets.QCheckBox(_t('guiTradSimpChinese', 'Use output target phrases if possible'))
        self.use_target_phrases.setToolTip(_t('guiTradSimpChinese', 'Check to allow region specific word replacements if available'))
        style_group_box_layout.addWidget(self.use_target_phrases)
        self.use_target_phrases.stateChanged.connect(self.update_gui)

        self.quotation_group_box = QtWidgets.QGroupBox(_t('guiTradSimpChinese', 'Quotation Marks'))
        widgetLayout.addWidget(self.quotation_group_box)
        quotation_group_box_layout = QtWidgets.QVBoxLayout()
        self.quotation_group_box.setLayout(quotation_group_box_layout)

        quotation_group=QtWidgets.QButtonGroup()
        self.quotation_no_conversion_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'No Conversion'))
        quotation_group.addButton(self.quotation_no_conversion_button)
        self.quotation_trad_to_simp_button = QtWidgets.QRadioButton(self.quote_for_simp_target)
        quotation_group.addButton(self.quotation_trad_to_simp_button)
        self.quotation_simp_to_trad_button = QtWidgets.QRadioButton(self.quote_for_trad_target)
        quotation_group.addButton(self.quotation_simp_to_trad_button)
        quotation_group_box_layout.addWidget(self.quotation_no_conversion_button)
        quotation_group_box_layout.addWidget(self.quotation_simp_to_trad_button)
        quotation_group_box_layout.addWidget(self.quotation_trad_to_simp_button)
        self.quotation_no_conversion_button.toggled.connect(self.update_gui)
        self.quotation_trad_to_simp_button.toggled.connect(self.update_gui)
        self.quotation_simp_to_trad_button.toggled.connect(self.update_gui)

        self.other_group_box = QtWidgets.QGroupBox(_t('guiTradSimpChinese', 'Other Changes'))
        widgetLayout.addWidget(self.other_group_box)
        other_group_box_layout = QtWidgets.QVBoxLayout()
        self.other_group_box.setLayout(other_group_box_layout)

        text_dir_layout = QtWidgets.QHBoxLayout()
        other_group_box_layout.addLayout(text_dir_layout)
        direction_label = QtWidgets.QLabel(_t('guiTradSimpChinese', 'Text Direction:'))
        text_dir_layout.addWidget(direction_label)
        self.text_dir_combo = QtWidgets.QComboBox()
        text_dir_layout.addWidget(self.text_dir_combo)
        self.text_dir_combo.addItems([_t('guiTradSimpChinese', 'No Conversion'),
                                      _t('guiTradSimpChinese', 'Horizontal'),
                                      _t('guiTradSimpChinese', 'Vertical')])
        self.text_dir_combo.setToolTip(_t('guiTradSimpChinese', 'Select the desired text orientation'))
        self.text_dir_combo.currentIndexChanged.connect(self.direction_changed)

        punctuation_layout = QtWidgets.QHBoxLayout()
        other_group_box_layout.addLayout(punctuation_layout)
        self.update_punctuation = QtWidgets.QCheckBox(_t('guiTradSimpChinese', 'Update punctuation'))
        punctuation_layout.addWidget(self.update_punctuation)
        self.update_punctuation.stateChanged.connect(self.update_gui)
        self.punc_settings_btn = QtWidgets.QPushButton()
        self.punc_settings_btn.setText("Settings...")

        punctuation_layout.addWidget(self.punc_settings_btn)
        self.punc_settings_btn.clicked.connect(self.punc_settings_btn_clicked)
        
        source_group=QtWidgets.QButtonGroup()
        self.book_source_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Entire eBook'))
        self.file_source_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Selected File(s)'))
        self.seltext_source_button = QtWidgets.QRadioButton(_t('guiTradSimpChinese', 'Selected Text in Selected File(s)'))
        self.seltext_source_button.setToolTip(_t('guiTradSimpChinese', '“Selected Text” is bracketed by <!--PI_SELTEXT_START--> and <!--PI_SELTEXT_END-->'))
        source_group.addButton(self.book_source_button)
        source_group.addButton(self.file_source_button)
        source_group.addButton(self.seltext_source_button)
        self.source_group_box = QtWidgets.QGroupBox(_t('guiTradSimpChinese', 'Source'))
        if not self.force_entire_book:
            widgetLayout.addWidget(self.source_group_box)
            source_group_box_layout = QtWidgets.QVBoxLayout()
            self.source_group_box.setLayout(source_group_box_layout)
            source_group_box_layout.addWidget(self.book_source_button)
            source_group_box_layout.addWidget(self.file_source_button)
            source_group_box_layout.addWidget(self.seltext_source_button)

        layout.addSpacing(10)
        self.button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        self.button_box.accepted.connect(self._ok_clicked)
        self.button_box.rejected.connect(self._reject_clicked)
        layout.addWidget(self.button_box)

        self.set_to_preferences()
        self.update_gui()

        self.show()


    def on_op_button_clicked(self, btn):
        self.block_signals(True)
        if btn == self.no_conversion_button:
            self.input_combo.setCurrentIndex(-1)  # blank out the entry
            self.output_combo.setCurrentIndex(-1) # blank out the entry
        else:
            self.input_combo.setCurrentIndex(0)   # mainland
            self.output_combo.setCurrentIndex(0)  # mainland
        self.block_signals(False)
        self.update_gui()

    def block_signals(self, state):
        # block or unblock the signals generated by these objects to avoid recursive calls
        self.input_combo.blockSignals(state)
        self.output_combo.blockSignals(state)
        self.no_conversion_button.blockSignals(state)
        self.trad_to_simp_button.blockSignals(state)
        self.simp_to_trad_button.blockSignals(state)
        self.trad_to_trad_button.blockSignals(state)
        self.file_source_button.blockSignals(state)
        self.seltext_source_button.blockSignals(state)
        self.book_source_button.blockSignals(state)
        self.quotation_trad_to_simp_button.blockSignals(state)
        self.quotation_simp_to_trad_button.blockSignals(state)
        self.quotation_no_conversion_button.blockSignals(state)
        self.text_dir_combo.blockSignals(state)
        self.update_punctuation.blockSignals(state)

    def update_gui(self):
        # callback to update other gui items when one changes
        if self.no_conversion_button.isChecked():
            self.input_combo.setEnabled(False)
            self.output_combo.setEnabled(False)
            self.input_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nNot Applicable'))
            self.output_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nNot Applicable'))
            self.use_target_phrases.setEnabled(False)
            self.output_region_label.setEnabled(False)
            self.input_region_label.setEnabled(False)
            self.style_group_box.setEnabled(False)

        elif self.trad_to_simp_button.isChecked():
            self.input_combo.setEnabled(True)
            self.output_combo.setEnabled(True)
            self.use_target_phrases.setEnabled(True)
            self.output_region_label.setEnabled(True)
            self.input_region_label.setEnabled(True)
            self.input_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nHong Kong/Mainland\nMainland/Mainland\nTaiwan/Mainland\nMainland/Japan'))
            self.output_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nHong Kong/Mainland\nMainland/Mainland\nTaiwan/Mainland\nMainland/Japan'))
            self.style_group_box.setEnabled(True)

        elif self.simp_to_trad_button.isChecked():
            self.input_combo.setEnabled(True)
            self.output_combo.setEnabled(True)
            self.input_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nMainland/Hong Kong\nMainland/Mainland\nMainland/Taiwan\nJapan/Mainland'))
            self.output_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nMainland/Hong Kong\nMainland/Mainland\nMainland/Taiwan\nJapan/Mainland'))
            self.use_target_phrases.setEnabled(True)
            self.output_region_label.setEnabled(True)
            self.input_region_label.setEnabled(True)
            self.style_group_box.setEnabled(True)

        elif self.trad_to_trad_button.isChecked():
            self.input_combo.setEnabled(True)
            self.output_combo.setEnabled(True)
            self.input_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nHong Kong/Mainland\nMainland/Hong Kong\nTaiwan/Mainland\nMainland/Taiwan\nMainland/Mainland\nHong Kong/Hong Kong\nTaiwan/Taiwan'))
            self.output_combo.setToolTip(_t('guiTradSimpChinese', 'Valid input/output combinations:\nHong Kong/Mainland\nMainland/Hong Kong\nTaiwan/Mainland\nMainland/Taiwan\nMainland/Mainland\nHong Kong/Hong Kong\nTaiwan/Taiwan'))
            self.use_target_phrases.setEnabled(True)
            self.output_region_label.setEnabled(True)
            self.input_region_label.setEnabled(True)
            self.style_group_box.setEnabled(True)

        if self.text_dir_combo.currentIndex() == 0:
            self.update_punctuation.blockSignals(True)
            self.update_punctuation.setChecked(False)
            self.update_punctuation.setEnabled(False)
            self.update_punctuation.blockSignals(False)
        else:
            self.update_punctuation.blockSignals(True)
            self.update_punctuation.setEnabled(True)
            self.update_punctuation.blockSignals(False)

        if self.update_punctuation.isChecked():
            self.punc_settings_btn.setEnabled(True)
        else:
            self.punc_settings_btn.setEnabled(False)

    def direction_changed(self):
        # callback when text direction changes
        self.update_punctuation.blockSignals(True)
        self.punc_settings_btn.blockSignals(True)

        if self.text_dir_combo.currentIndex() == 0:    # no direction change
            self.update_punctuation.setChecked(False)
            self.update_punctuation.setEnabled(False)
            self.punc_settings_btn.setEnabled(False)

        else:
            self.update_punctuation.setChecked(True)
            self.update_punctuation.setEnabled(True)
            self.punc_settings_btn.setEnabled(True)

        self.punc_settings_btn.blockSignals(False)
        self.update_punctuation.blockSignals(False)

    def set_to_preferences(self):
        # set the gui values to match those in the preferences
        self.block_signals(True)

        self.input_combo.setCurrentIndex(self.prefs['input_locale'])
        self.output_combo.setCurrentIndex(self.prefs['output_locale'])

        if self.prefs['conversion_type'] == 0:
            self.no_conversion_button.setChecked(True)
        elif self.prefs['conversion_type'] == 1:
            self.trad_to_simp_button.setChecked(True)
        elif self.prefs['conversion_type'] == 2:
            self.simp_to_trad_button.setChecked(True)
        else:
            self.trad_to_trad_button.setChecked(True)

        if not self.force_entire_book:
            if self.prefs['input_source'] == 1:
                self.file_source_button.setChecked(True)
            elif self.prefs['input_source'] == 2:
                self.seltext_source_button.setChecked(True)
            else:
                self.book_source_button.setChecked(True)
        else:
            self.book_source_button.setChecked(True)
            self.file_source_button.setChecked(False)
            self.seltext_source_button.setChecked(False)

        if self.prefs['quotation_type'] == 1:
            self.quotation_trad_to_simp_button.setChecked(True)
        elif self.prefs['quotation_type'] == 2:
            self.quotation_simp_to_trad_button.setChecked(True)
        else:
            self.quotation_no_conversion_button.setChecked(True)

        self.text_dir_combo.setCurrentIndex(self.prefs['output_orientation'])
        if self.text_dir_combo.currentIndex() == 0:
            self.update_punctuation.setChecked(False)
        else:
            self.update_punctuation.setChecked(self.prefs['update_punctuation'])

        self.block_signals(False)

    def savePrefs(self):
        # save the current settings into the preferences
        self.prefs['input_locale'] = self.input_combo.currentIndex()
        self.prefs['output_locale'] = self.output_combo.currentIndex()

        if self.trad_to_simp_button.isChecked():
            self.prefs['conversion_type'] = 1
        elif self.simp_to_trad_button.isChecked():
            self.prefs['conversion_type'] = 2
        elif self.trad_to_trad_button.isChecked():
            self.prefs['conversion_type'] = 3
        else:
            self.prefs['conversion_type'] = 0

        if self.file_source_button.isChecked():
            self.prefs['input_source'] = 1
        elif self.seltext_source_button.isChecked():
            self.prefs['input_source'] = 2
        else:
            self.prefs['input_source'] = 0

        self.prefs['use_target_phrases'] = self.use_target_phrases.isChecked()

        if self.quotation_trad_to_simp_button.isChecked():
            self.prefs['quotation_type'] = 1
        elif self.quotation_simp_to_trad_button.isChecked():
            self.prefs['quotation_type'] = 2
        else:
            self.prefs['quotation_type'] = 0

        self.prefs['output_orientation'] = self.text_dir_combo.currentIndex()
        self.prefs['update_punctuation'] = self.update_punctuation.isChecked()

    def _reject_clicked(self):
        # restore initial settings and close dialog
        self.set_to_preferences()
        self.update_gui()
        self.close()

    def _ok_clicked(self):

        # save current settings into preferences and close dialog
        self.savePrefs()

        self.filesChanged = False
        self.changed_files = []

        criteria = self.getCriteria()
        # Ensure any in progress editing the user is doing is present in the container
        # Checkpoint 
        # self.boss.commit_all_editors_to_container()
        # self.boss.add_savepoint(_('Before: Text Conversion')) #checkpoint support for plugin is not available in Sigil

        # Set the conversion output language
        self.language = get_language_code(criteria)
        if self.language != "None":
            self.parser.setLanguageAttribute('lang=\"' + self.language + '\"')
        else:
            self.parser.setLanguageAttribute(None)

        try:
            conversion = get_configuration(criteria)
    ##                print("Conversion: ", conversion);
            if conversion == 'unsupported_conversion':
                dlg = QtWidgets.QMessageBox(icon = QtWidgets.QMessageBox.Warning)
                dlg.setWindowTitle(_t('guiTradSimpChinese', "No Changes"))
                dlg.setText(_t('guiTradSimpChinese', "The output configuration selected is not supported.\n Please use a different Input/Output Language Styles combination"))
                dlg.exec()
            else:
                QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(Qt.WaitCursor))
                QtWidgets.QApplication.processEvents()
                self.converter.set_conversion(conversion)
                self.process_files(criteria)
                QtWidgets.QApplication.restoreOverrideCursor()
        except Exception:
            QtWidgets.QApplication.restoreOverrideCursor()
            # Something bad happened report the error to the user
            import traceback
            dlg = QtWidgets.QMessageBox(icon = QtWidgets.QMessageBox.Critical)
            dlg.setWindowTitle(_t('guiTradSimpChinese', "Failed"))
            dlg.setText(_t('guiTradSimpChinese', 'Failed to convert Chinese, click "Show details" for more info'))
            dlg.setDetailedText(traceback.format_exc())
            dlg.exec()

            # Revert to the saved restore point
            # self.boss.revert_requested(self.boss.global_undo.previous_container)
        else:
            if self.filesChanged:
                dlg = QtWidgets.QMessageBox()
                dlg.setWindowTitle(_t('guiTradSimpChinese', "Changed Files"))
                dlg.setText(f"A total of {len(self.changed_files)} files have been converted.")
                dlg.exec()
                self.close()
            elif conversion != 'unsupported_conversion':
                dlg = QtWidgets.QMessageBox(icon = QtWidgets.QMessageBox.Information)
                dlg.setWindowTitle(_t('guiTradSimpChinese', "No Changes"))
                dlg.setText(_t('guiTradSimpChinese', "No text meeting your criteria was found to change.\nNo changes made."))
                dlg.exec()

    def process_files(self, criteria):

        if criteria[INPUT_SOURCE] == 1 or criteria[INPUT_SOURCE] == 2:
            for (typ, ident) in self.bk.selected_iter():
                # Skip the ones that aren't the "Text" mimetype.
                if self.bk.id_to_mime(ident) != 'application/xhtml+xml':
                    continue
                href = self.bk.id_to_href(ident)

                data = self.bk.readfile(ident)
                if not isinstance(data, str):
                    data = str(data, 'utf-8')

                htmlstr = self.parser.processText(data, criteria)
                if htmlstr != data:
                    self.filesChanged = True
                    self.changed_files.append(href)
                    self.bk.writefile(ident, htmlstr)

        elif criteria[INPUT_SOURCE] == 0:

            # Cover the entire book
            # Set metadata and Table of Contents (TOC) if language changed
            if criteria[CONVERSION_TYPE] != 0:
                self.filesChanged = self.set_metadata_toc(criteria)

            if criteria[OUTPUT_ORIENTATION] != 0 and len(list(self.bk.css_iter())) == 0:
                self.filesChanged = True
                self.bk.addfile("css", "stylesheet.css", "")
                self.parser.force_stylesheet = True

            dlg = ShowProgressDialog(self.bk, criteria, self.parser.processText, _t('guiTradSimpChinese', 'Converting'))
            self.changed_files.extend(dlg.changed_files)

            self.parser.force_stylesheet = False

            # Check for orientation change
            direction_changed = False
            if criteria[OUTPUT_ORIENTATION] != 0:
                direction_changed = set_flow_direction(self.bk, criteria, self.changed_files, self.converter)

            self.filesChanged = self.filesChanged or (not dlg.clean) or direction_changed


        

    def getCriteria(self):
        # Get the criteria from the current saved preferences if not passed in
        # The preference set is updated every time the user dialog is closed

        punc_dict = {}
        punc_regex = None

        if self.prefs['update_punctuation'] and (len(self.prefs['punc_omits']) != len(_h2v_master_dict.keys())):
            # create a dictionary without the keys contained in self.prefs['punc_omits']
            h2v = {}
            omit_set = set(self.prefs['punc_omits'])
            for key in _h2v_master_dict.keys():
                if not key in omit_set:
                    h2v[key] = _h2v_master_dict[key]

            # horizontal full width characters to their vertical presentation forms regex
            h2v_dict_regex = re.compile("(%s)" % "|".join(map(re.escape, h2v.keys())))

            # vertical full width characters to their horizontal presentation forms regex
            v2h = {v: k for k, v in h2v.items()}
            v2h_dict_regex = re.compile("(%s)" % "|".join(map(re.escape, v2h.keys())))

            if self.prefs['output_orientation'] == 1:
                punc_dict = v2h
                punc_regex = v2h_dict_regex
            elif self.prefs['output_orientation'] == 2:
                punc_dict = h2v
                punc_regex = h2v_dict_regex

        criteria = (
            self.prefs['input_source'], self.prefs['conversion_type'], self.prefs['input_locale'],
            self.prefs['output_locale'], self.prefs['use_target_phrases'], self.prefs['quotation_type'],
            self.prefs['output_orientation'], self.prefs['update_punctuation'], punc_dict, punc_regex)

        return criteria
    
    def set_metadata_toc(self, criteria):
    # Returns True if either the metadata or TOC files changed
    # changed_files is updated

        metadataChanged = False
        tocChanged = False

        # List of dc items in OPF file that get a simple text replacement
        # Add more items to this list if needed
        # '//opf:metadata/dc:title'

        dc_list = ['title', 'description', 'publisher', 'subject' 'contributor', 'coverage', 'rights']
        
        import xml.etree.ElementTree as ET
        tree = ET.ElementTree(ET.fromstring(self.bk.getmetadataxml()))
        root = tree.getroot()

        for item in root.iter():
            _, *tag = item.tag.split("}")
            tag = tag[0] if tag else None

            # Only update the dc language if the original language was a Chinese type and epub format
            if tag == "language" and (re.search('zh-\w+|zh', item.text, flags=re.IGNORECASE) != None):
                old_text = item.text
                item.text = self.language
                if item.text != old_text:
                    metadataChanged = True

            # Update the creator text and file-as attribute
            elif tag == "creator":
                old_text = item.text
                if (item.text != None):
                    item.text = self.converter.convert(item.text)
                    if item.text != old_text:
                        metadataChanged = True
                for attrib in item.attrib:
                    item.attrib[attrib] = self.converter.convert(item.attrib[attrib])

            elif tag in dc_list:
                old_text = item.text
                if (item.text != None):
                    item.text = self.converter.convert(item.text)
                    if item.text != old_text:
                        metadataChanged = True


        tocid = self.bk.gettocid()
        href = self.bk.id_to_href(tocid)
        data = self.bk.readfile(tocid)
        if not isinstance(data, str):
            data = str(data, 'utf-8')

        dummy_criteria = list(criteria)
        dummy_criteria[OUTPUT_ORIENTATION] = 0

        htmlstr = self.parser.processText(data, criteria)
        if htmlstr != data:
            self.tocChanged = True
            self.changed_files.append(href)
            self.bk.writefile(tocid, htmlstr)

        # toc_tree = ET.ElementTree(ET.fromstring(data))
        # toc_root = toc_tree.getroot()

        # # Update the TOC - Do this after modifying the OPF data
        # # Just grab all <text> fields (AKA "title" attribute in a TOC object)
        # # and convert to the desired Chinese.

        # for item in toc_root.iter():

        #     _, *tag = item.tag.split("}")
        #     tag = tag[0] if tag else None

        #     if tag == "text" and item.text != None:
        #         old_text = item.text
        #         item.text = converter.convert(item.text)
        #         if old_text != item.text:
        #             tocChanged = True

        # Update the files with the changes

        if metadataChanged:
            xml_str = ET.tostring(root, encoding='unicode')
            self.bk.setmetadataxml(xml_str)

        return(tocChanged or metadataChanged)

    def punc_settings_btn_clicked(self):
        # open the punctuation dialog
        self.punctuation_dialog.exec()

def get_language_code(criteria):
    """
    :param criteria: the description of the desired conversion
    :return: 'zh-CN', 'zh-TW', 'zh-HK', or 'None'
    """
    conversion_mode = criteria[CONVERSION_TYPE]
    input_type = criteria[INPUT_LOCALE]
    output_type = criteria[OUTPUT_LOCALE]

    # Return 'None' if Japan locale is used so that no laguage changes are made
    language_code = 'None'

    if conversion_mode == 1:
        #trad to simp
        if output_type == 0:
            language_code = 'zh-CN'

    elif conversion_mode == 2:
        #simp to trad, (we don't support Macau yet zh-MO)
        if output_type == 0:
            language_code = 'zh-CN'
        elif output_type == 1:
            language_code = 'zh-HK'
        else:
            language_code = 'zh-TW'

    elif conversion_mode == 3:
        #trad to trad, (we don't support Macau yet zh-MO)
        if input_type == 0:
            if output_type == 1:
                language_code = 'zh-HK'
            elif output_type == 2:
                language_code = 'zh-TW'
            else:
                #mainland trad -> mainland trad does nothing
                language_code = 'None'
        elif input_type == 1:
            if output_type == 0:
                language_code = 'zh-CN'
            else:
                #only TW trad -> mainland
                language_code = 'None'
        elif input_type == 2:
            if output_type == 0:
                language_code = 'zh-CN'
            else:
                #only HK trad -> mainland
                language_code = 'None'
        else:
            #hk -> tw and tw -> hk not currently set up
            #hk -> hk and tw -> tw does nothing
            language_code = 'None'
    return language_code


def add_flow_direction_properties(rule, orientation_value, break_value):
    rule_changed = False
    if rule.style['writing-mode'] != orientation_value:
        rule.style['writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['-epub-writing-mode'] != orientation_value:
        rule.style['-epub-writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['-webkit-writing-mode'] != orientation_value:
        rule.style['-webkit-writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['line-break'] != break_value:
        rule.style['line-break'] = break_value
        rule_changed = True

    if rule.style['-webkit-line-break'] != break_value:
        rule.style['-webkit-line-break'] = break_value
        rule_changed = True

    return rule_changed

def set_flow_direction(bk, criteria, changed_files, converter):
    # Open OPF and set flow
    flow = 'default'
    if criteria[OUTPUT_ORIENTATION] == 2:
        flow = 'rtl'
    elif criteria[OUTPUT_ORIENTATION] == 1:
        flow = 'ltr'

    old_flow = bk.getspine_ppd()
    bk.setspine_ppd(flow)
    fileChanged = (old_flow != flow)

    # Open CSS and set layout direction in the body section
    if criteria[OUTPUT_ORIENTATION] == 1:
        orientation = 'horizontal-tb'
        break_rule = 'auto'
    if criteria[OUTPUT_ORIENTATION] == 2:
        orientation = 'vertical-rl'
        break_rule = 'normal'

    addedCSSRules = False

    for id, href in bk.css_iter():
        data = bk.readfile(id)
        sheet = css_parser.parseString(data)
        rules = (rule for rule in sheet if rule.type == rule.STYLE_RULE)
        for rule in rules:
            for selector in rule.selectorList:
                if selector.selectorText == u'.calibre':
                    addedCSSRules = True
                    if add_flow_direction_properties(rule, orientation, break_rule):
                        fileChanged = True
                        changed_files.append(href)
                        bk.writefile(id, sheet.cssText)
                    break

    if not addedCSSRules:
        for id, href in bk.css_iter():
            data = bk.readfile(id)
            sheet = css_parser.parseString(data)
            rules = (rule for rule in sheet if rule.type == rule.STYLE_RULE)
            for rule in rules:
                for selector in rule.selectorList:
                    if selector.selectorText == u'body':
                        addedCSSRules = True
                        if add_flow_direction_properties(rule, orientation, break_rule):
                            fileChanged = True
                            changed_files.append(href)
                            bk.writefile(id, sheet.cssText)

    # If no 'body' selector rule is found in any css file, add one to every css file
    if not addedCSSRules:
        for id, href in bk.css_iter():
            data = bk.readfile(id)
            sheet = css_parser.parseString(data)
            # Create a style rule for body.
            styleEntry = css_parser.css.CSSStyleDeclaration()
            styleEntry['writing-mode'] = orientation
            styleRule = css_parser.css.CSSStyleRule(selectorText=u'body', style=styleEntry)
            sheet.add(styleRule)
            styleRule.style['-epub-writing-mode'] = orientation
            styleRule.style['-webkit-writing-mode'] = orientation
            styleRule.style['line-break'] = break_rule
            styleRule.style['-webkit-line-break'] = break_rule
            fileChanged = True
            changed_files.append(href)
            bk.writefile(id, sheet.cssText)
    return fileChanged

def add_flow_direction_properties(rule, orientation_value, break_value):
    rule_changed = False
    if rule.style['writing-mode'] != orientation_value:
        rule.style['writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['-epub-writing-mode'] != orientation_value:
        rule.style['-epub-writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['-webkit-writing-mode'] != orientation_value:
        rule.style['-webkit-writing-mode'] = orientation_value
        rule_changed = True

    if rule.style['line-break'] != break_value:
        rule.style['line-break'] = break_value
        rule_changed = True

    if rule.style['-webkit-line-break'] != break_value:
        rule.style['-webkit-line-break'] = break_value
        rule_changed = True

    return rule_changed

def get_configuration(criteria):
    """
    :param criteria: the description of the desired conversion
    :return a tuple of the conversion direction and the output format:
      1) 'hk2s', 'hk2t', 'jp2t', 's2hk', 's2t', 's2tw', 's2twp', 't2hk', 't2hkp', 't2jp', 't2s', 't2tw', 'tw2s', 'tw2sp', 'tw2t', 'no_conversion', or 'unsupported_conversion'
    """
    conversion_mode = criteria[CONVERSION_TYPE]
    input_type = criteria[INPUT_LOCALE]
    output_type = criteria[OUTPUT_LOCALE]
    use_target_phrasing = criteria[USE_TARGET_PHRASES]

    configuration = 'unsupported_conversion'

    if conversion_mode == 0:
        #no conversion desired
        configuration = 'no_conversion'

    elif conversion_mode == 1:
        #trad to simp
        if input_type == 0:         # mainland
            if output_type == 0:    # mainland
                configuration = 't2s'
            elif output_type == 3:     # Japan
                configuration = 't2jp' # traditional Chinese hanzi to simplified modern Japanese kanji
            else: # HK or TW
                configuration = 'unsupported_conversion'
        elif input_type == 1:       # Hong Kong
            if output_type != 0:    # not mainland
                configuration = 'unsupported_conversion'
            else:
                configuration = 'hk2s'
        elif input_type == 2:       # Taiwan
            if output_type != 0:    # not mainland
                configuration = 'unsupported_conversion'
            else:
                configuration = 'tw2s'
                if use_target_phrasing:
                    configuration += 'p'
        else:
            # Japan is simplified kanji only
            configuration = 'unsupported_conversion'

    elif conversion_mode == 2:
        #simp to trad
        if input_type == 0:             #mainland
            if output_type == 0:        # mainland
                configuration = 's2t'
            elif output_type == 1:      # Hong Kong
                configuration = 's2hk'
            elif output_type == 2:       # Taiwan
                configuration = 's2tw'
                if use_target_phrasing:
                    configuration += 'p'
            else:
                # Japan
                configuration = 'unsupported_conversion'
        elif input_type == 3:          # Japan
            if output_type == 0:       # mainland
                configuration = 'jp2t' #Simplified modern Japanese kanji to traditional Chinese hanzi
            else:
                # HK or TW
                configuration = 'unsupported_conversion'
        else:
            # HK or TW are traditional only
            configuration = 'unsupported_conversion'

    else:
        #trad to trad
        if input_type == 0:             # mainland
            if output_type == 0:        # mainland
                configuration = 'no_conversion' # does nothing
            elif output_type == 1:        # Hong Kong
                configuration = 't2hk'
            elif output_type == 2:      # Taiwan
                configuration = 't2tw'
            else:                       # mainland
                # Japan is invalid
                configuration = 'unsupported_conversion'
        elif input_type == 1:           # Hong Kong
            if output_type == 0:
                configuration = 'hk2t'
            elif output_type == 1:        # Hong Kong
                configuration = 'no_conversion' # does nothing
            else:
                #HK trad -> TW trad not supported, Japan is invalid
                configuration = 'unsupported_conversion'
        elif input_type == 2:           # Taiwan
            if output_type == 0:
                configuration = 'tw2t'
            elif output_type == 2:        # Taiwan
                configuration = 'no_conversion' # does nothing
            else:
                #TW trad -> HK trad not supported, Japan is invalid
                configuration = 'unsupported_conversion'
        else:
            #JP is simplified kanji only
            configuration = 'unsupported_conversion'

    return configuration


class ShowProgressDialog(QtWidgets.QProgressDialog):
    def __init__(self, bk, criteria, callback_fn, action_type='Checking'):
        self.file_list = list(bk.text_iter())
        self.clean = True
        self.changed_files = []
        self.total_count = len(self.file_list)
        super().__init__('', _t("ShowProgressDialog", 'Cancel'), 0, self.total_count)
        self.setMinimumWidth(500)
        self.bk, self.criteria, self.callback_fn, self.action_type = bk, criteria, callback_fn, action_type
        self.setWindowTitle('{0}...'.format(self.action_type))
        self.i = 0
        
        QtCore.QTimer.singleShot(0, self.do_action)
        self.exec()

    def do_action(self):

        if self.wasCanceled():
            return self.do_close()
        if self.i >= self.total_count:
            return self.do_close()

        id, href = self.file_list[self.i]

        data = self.bk.readfile(id)
        self.i += 1

        self.setLabelText('{0}: {1}'.format(self.action_type, href))
        # Send the necessary data to the callback function in main.py.
        htmlstr = self.callback_fn(data, self.criteria)
        if htmlstr != data:
            self.changed_files.append(href)
            self.bk.writefile(id, htmlstr)
            self.clean = False

        self.setValue(self.i)

        # Lather, rinse, repeat
        QtCore.QTimer.singleShot(0, self.do_action)

    def do_close(self):
        self.close()

def run(bk):
            
    print("Entered Target Script run() routine")



    # Setting the proper Return value is important.
    # 0 - means success
    # anything else means failure



    icon = os.path.join(os.path.dirname(__file__), 'plugin.png')

    mdp = True if iswindows else False
    app = PluginApplication(sys.argv, bk, app_icon = icon, match_dark_palette=mdp,
                            dont_use_native_menubars=True)

    win = guiTradSimpChinese(bk)
    # Use exec() and not exec_() for PyQt5/PySide6 compliance
    app.exec()
        

    return 0

def main():
    print("I reached main when I should not have\n")
    return -1

if __name__ == "__main__":
    sys.exit(main())