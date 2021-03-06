#########################
# Imports

# python standard libraries
from collections import deque
from collections import OrderedDict as odict
import copy
import sys
import time
import threading
import pdb


# other required libraries
import numpy as np

# Using PySide (Qt) to build GUI
from PySide2 import QtCore, QtGui, QtWidgets

# import whole module so pyqtgraph recognizes we're using it
import PySide2
# using pyqtgraph for data visualization
import pyqtgraph as pg

# import styles
import gui_styles

##########################
# GUI Class

try:
    mono_font = QtGui.QFont('Fira Code')
except:
    mono_font = QtGui.QFont()
    mono_font.setStyleHint(QtGui.QFont.Monospace)


class Vent_Gui(QtWidgets.QMainWindow):
    """

    Controls:
        - PIP: peak inhalation pressure (~20 cm H2O)
        - T_insp: inspiratory time to PEEP (~0.5 sec)
        - I/E: inspiratory to expiratory time ratio
        - bpm: breaths per minute (15 bpm -> 1/15 sec cycle time)
        - PIP_time: Target time for PIP. While lungs expand, dP/dt should be PIP/PIP_time
        - flow_insp: nominal flow rate during inspiration

    **Set by hardware**
        - FiO2: fraction of inspired oxygen, set by blender
        - max_flow: manual valve at output of blender
        - PEEP: positive end-expiratory pressure, set by manual valve

    **Derived parameters**
        - cycle_time: 1/bpm
        - t_insp: inspiratory time, controlled by cycle_time and I/E
        - t_exp: expiratory time, controlled by cycle_time and I/E

    **Monitored variables**
        * O2
        * Temperature
        * Humidity
        - (VTE) End-Tidal volume: the volume of air entering the lung, derived from flow through t_exp
        - PIP: peak inspiratory pressure, set by user in software
        - Mean plateau pressure: derived from pressure sensor during inspiration cycle hold (no flow)
        - PEEP: positive end-expiratory pressure, set by manual valve
        * fTotal (total respiratory frequency) - breaths delivered by vent & patients natural breaths


    **Alarms**
        - Oxygen out of range
        - High pressure (tube/airway occlusion)
        - Low-pressure (disconnect)
        - Temperature out of range
        - Low voltage alarm (if using battery power)
        - Tidal volume (expiratory) out of range


    Graphs:
        * Flow
        * Pressure

    """

    DISPLAY = odict({
        'oxygen': {
            'name': 'O2 Concentration',
            'units': '%',
            'abs_range': (0, 100),
            'safe_range': (60, 100),
            'decimals' : 1
        },
        'temperature': {
            'name': 'Temperature',
            'units': '\N{DEGREE SIGN}C',
            'abs_range': (0, 50),
            'safe_range': (20, 30),
            'decimals': 1
        },
        'humidity': {
            'name': 'Humidity',
            'units': '%',
            'abs_range': (0, 100),
            'safe_range': (20, 75),
            'decimals': 1
        },
        'vte': {
            'name': 'VTE',
            'units': '%',
            'abs_range': (0, 100),
            'safe_range': (20, 80),
            'decimals': 1
        },
        'etc': {
            'name': 'Other measurements??',
            'units': '???',
            'abs_range': (0, 100),
            'safe_range': (10, 90),
            'decimals': 1
        }
    })

    PLOTS = {
        'flow': {
            'name': 'Flow (L/s)',
            'abs_range': (0, 100),
            'safe_range': (20, 80),
            'color': gui_styles.SUBWAY_COLORS['yellow'],
        },
        'pressure': {
            'name': 'Pressure (mmHg)',
            'abs_range': (0, 100),
            'safe_range': (20, 80),
            'color': gui_styles.SUBWAY_COLORS['orange'],
        }
    }

    def __init__(self, update_period = 0.1):
        super(Vent_Gui, self).__init__()

        self.display_values = {}
        self.plots = {}
        self.controls = {}

        self.update_period = update_period

        self.init_ui()
        self.start_time = time.time()

        self.test()


    def test(self):

        ox = ((np.sin(time.time()/10)+1)*5)+80
        self.display_values['oxygen'].update_value(ox)

        temp = ((np.sin(time.time()/20)+1)*2.5)+22
        self.display_values['temperature'].update_value(temp)

        humid = ((np.sin(time.time()/50)+1)*5)+50
        self.display_values['humidity'].update_value(humid)

        press = (np.sin(time.time())+1)*25
        self.display_values['vte'].update_value(press)
        self.plots['pressure'].update_value((time.time(), press))
        # for num, widget in enumerate(self.display_values.values()):
        #     yval = (np.sin(time.time()+num) + 1) * 50
        #     widget.update_value(yval)
        self.plots['flow'].update_value((time.time(),(np.sin(time.time()) + 1) * 50))


        # if (time.time()-self.start_time) < 60:
        QtCore.QTimer.singleShot(0.01, self.test)


    def update_value(self, value_name, new_value):
            if value_name in self.display_values.keys():
                self.display_values[value_name].update_value(new_value)
            elif value_name in self.plots.keys():
                self.plots[value_name].update_value(new_value)

    def init_ui(self):
        """
        Create the UI components for the ventilator screen
        """

        # basic initialization


        self.main_widget = QtWidgets.QWidget()
        #
        self.setCentralWidget(self.main_widget)

        # layout - three columns
        # left: readout values
        # left: readout values
        # center: plotted values
        # right: controls & limits
        self.layout = QtWidgets.QHBoxLayout()
        self.main_widget.setLayout(self.layout)

        #########
        # display values
        self.display_layout = QtWidgets.QVBoxLayout()

        for display_key, display_params in self.DISPLAY.items():
            self.display_values[display_key] = Display_Value(update_period = self.update_period, **display_params)
            self.display_layout.addWidget(self.display_values[display_key])
            self.display_layout.addWidget(QHLine())
        self.layout.addLayout(self.display_layout, 1)


        # plots
        self.plot_layout = QtWidgets.QVBoxLayout()

        # button to set plot history
        button_box = QtWidgets.QGroupBox("Plot History")
        #button_group = QtWidgets.QButtonGroup()
        #button_group.exclusive()
        times = (("5s", 5),
                 ("10s", 10),
                 ("30s", 30),
                 ("1m", 60),
                 ("5m", 60*5),
                 ("15m", 60*15),
                 ("60m", 60*60))

        self.time_buttons = {}
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        for a_time in times:
            self.time_buttons[a_time[0]] = QtWidgets.QRadioButton(a_time[0])
            #self.time_buttons[a_time[0]].setCheckable(True)
            self.time_buttons[a_time[0]].setObjectName(str(a_time[1]))
            self.time_buttons[a_time[0]].clicked.connect(self.set_plot_duration)
            button_layout.addWidget(self.time_buttons[a_time[0]])
            #button_group.addButton(self.time_buttons[a_time[0]])

        button_box.setLayout(button_layout)
        self.plot_layout.addWidget(button_box)


        for plot_key, plot_params in self.PLOTS.items():
            self.plots[plot_key] = Plot(**plot_params)
            self.plot_layout.addWidget(self.plots[plot_key])
        self.layout.addLayout(self.plot_layout,2)


        # connect displays to plots
        self.display_values['vte'].limits_changed.connect(self.plots['pressure'].set_safe_limits)
        self.plots['pressure'].limits_changed.connect(self.display_values['vte'].update_limits)

        self.show()

    def set_plot_duration(self, dur):
        dur = int(self.sender().objectName())

        for plot in self.plots.values():
            plot.set_duration(dur)



class Display_Value(QtWidgets.QWidget):
    alarm = QtCore.Signal()
    limits_changed = QtCore.Signal(tuple)

    def __init__(self, name, units, abs_range, safe_range, decimals, update_period=0.1):
        super(Display_Value, self).__init__()

        self.name = name
        self.units = units
        self.abs_range = abs_range
        self.safe_range = safe_range
        self.decimals = decimals
        self.update_period = update_period

        self.value = None

        self.init_ui()

        self.timed_update()

    def init_ui(self):
        self.layout = QtWidgets.QHBoxLayout()
        self.setLayout(self.layout)

        #########
        # create widgets
        # make range slider
        self.range_slider = RangeSlider(self.abs_range, self.safe_range)

        # make comboboxes to display numerical value
        self.max_safe = QtWidgets.QSpinBox()
        self.max_safe.setRange(self.abs_range[0], self.abs_range[1])
        self.max_safe.setSingleStep(10 ** (self.decimals * -1))
        self.max_safe.setValue(self.safe_range[1])

        self.min_safe = QtWidgets.QSpinBox()
        self.min_safe.setRange(self.abs_range[0], self.abs_range[1])
        self.min_safe.setSingleStep(10 ** (self.decimals * -1))
        self.min_safe.setValue(self.safe_range[0])

        # labels to display values
        self.value_label = QtWidgets.QLabel()
        self.value_label.setStyleSheet(gui_styles.DISPLAY_VALUE)
        self.value_label.setFont(mono_font)
        self.value_label.setAlignment(QtCore.Qt.AlignRight)
        self.value_label.setMargin(0)
        self.value_label.setContentsMargins(0,0,0,0)

        self.name_label = QtWidgets.QLabel()
        self.name_label.setStyleSheet(gui_styles.DISPLAY_NAME)
        self.name_label.setText(self.name)
        self.name_label.setAlignment(QtCore.Qt.AlignRight)

        self.units_label = QtWidgets.QLabel()
        self.units_label.setStyleSheet(gui_styles.DISPLAY_UNITS)
        self.units_label.setText(self.units)
        self.units_label.setAlignment(QtCore.Qt.AlignRight)

        #########
        # connect widgets

        # update boxes when slider changed
        self.range_slider.valueChanged.connect(self.update_boxes)

        # and vice versa
        self.min_safe.valueChanged.connect(self.range_slider.setLow)
        self.max_safe.valueChanged.connect(self.range_slider.setHigh)

        # and connect them all to a general limits_changed method
        # that also checks the alarm
        self.range_slider.valueChanged.connect(self._limits_changed)
        self.min_safe.valueChanged.connect(self._limits_changed)
        self.max_safe.valueChanged.connect(self._limits_changed)

        #########
        # layout widgets
        self.layout.addWidget(self.range_slider, 2)

        box_layout = QtWidgets.QVBoxLayout()
        box_layout.addWidget(QtWidgets.QLabel('Max:'))
        box_layout.addWidget(self.max_safe)
        box_layout.addStretch()
        box_layout.addWidget(QtWidgets.QLabel('Min:'))
        box_layout.addWidget(self.min_safe)
        self.layout.addLayout(box_layout, 1)

        label_layout = QtWidgets.QVBoxLayout()
        label_layout.setContentsMargins(0,0,0,0)
        label_layout.addWidget(self.value_label)
        label_layout.addWidget(self.name_label)
        label_layout.addWidget(self.units_label)
        label_layout.addStretch()
        self.layout.addLayout(label_layout, 5)


    def update_boxes(self, new_values):
        self.min_safe.setValue(new_values[0])
        self.max_safe.setValue(new_values[1])

    @QtCore.Slot(int)
    @QtCore.Slot(float)
    def update_value(self, new_value):

        # stash numerical value
        self.value = new_value
        self.check_alarm()
        self.range_slider.update_indicator(new_value)

    @QtCore.Slot(tuple)
    def update_limits(self, new_limits):
        self.range_slider.setLow(new_limits[0])
        self.range_slider.setHigh(new_limits[1])
        self.update_boxes(new_limits)

    def timed_update(self):
        # format value based on decimals
        if self.value:
            value_str = str(np.round(self.value, self.decimals))
            self.value_label.setText(value_str)

        QtCore.QTimer.singleShot(round(self.update_period*1000), self.timed_update)

    def _limits_changed(self, val):
        # ignore value, just emit changes and check alarm
        self.check_alarm()
        self.limits_changed.emit((self.min_safe.value(), self.max_safe.value()))

    def check_alarm(self, signal=None):
        if self.value:
            if (self.value >= self.max_safe.value()) or (self.value <= self.min_safe.value()):
                self.alarm.emit()
                self.value_label.setStyleSheet(gui_styles.DISPLAY_VALUE_ALARM)
                self.range_slider.alarm = True
            else:
                self.value_label.setStyleSheet(gui_styles.DISPLAY_VALUE)
                self.range_slider.alarm = False








class RangeSlider(QtWidgets.QSlider):
    """
    A slider for ranges.
    This class provides a dual-slider for ranges, where there is a defined
    maximum and minimum, as is a normal slider, but instead of having a
    single slider value, there are 2 slider values.
    This class emits the same signals as the QSlider base class, with the
    exception of valueChanged

    Adapted from https://bitbucket.org/genuine_/idascope-local/src/master/idascope/widgets/RangeSlider.py
    (Thank you!!!)

    With code from https://stackoverflow.com/a/54819051
    for labels!
    """

    valueChanged = QtCore.Signal(tuple)

    def __init__(self, abs_range, safe_range, *args):
        super(RangeSlider, self).__init__(*args)
        self.setStyleSheet(gui_styles.RANGE_SLIDER)

        self.abs_range = abs_range
        self.setMinimum(abs_range[0])
        self.setMaximum(abs_range[1])
        #self.setTickInterval(round((abs_range[1]-abs_range[0])/5))
        #self.setTickPosition(QtWidgets.QSlider.TicksLeft)

        self.safe_range = safe_range
        self.low = safe_range[0]
        self.high = safe_range[1]

        #self._low = self.minimum()
        #self._high = self.maximum()

        self._alarm = False

        self.pressed_control = QtWidgets.QStyle.SC_None
        self.hover_control = QtWidgets.QStyle.SC_None
        self.click_offset = 0

        # 0 for the low, 1 for the high, -1 for both
        self.active_slider = 0

        # ticks
        self.setTickPosition(QtWidgets.QSlider.TicksLeft)
        # gives some space to print labels
        self.left_margin=10
        self.top_margin=10
        self.right_margin=0
        self.bottom_margin=10
        self.setContentsMargins(self.left_margin,
                                self.top_margin,
                                self.right_margin,
                                self.bottom_margin)
        self.setMinimumWidth(gui_styles.SLIDER_WIDTH)

        # indicator
        self._indicator = 0


    @property
    def low(self):
        return self._low

    @low.setter
    def low(self, low):
        self._low = low
        self.update()

    @property
    def high(self):
        return self._high

    @high.setter
    def high(self, high):
        self._high = high
        self.update()

    # make methods just so the can accept signals
    def setLow(self, low):
        self.low = low

    def setHigh(self, high):
        self.high = high

    def update_indicator(self, new_val):
        self._indicator = new_val
        self.update()

    @property
    def alarm(self):
        return self._alarm

    @alarm.setter
    def alarm(self, alarm):
        self._alarm = alarm
        self.update()


    def paintEvent(self, event):
        # based on http://qt.gitorious.org/qt/qt/blobs/master/src/gui/widgets/qslider.cpp

        painter = QtGui.QPainter(self)
        #style = QtWidgets.QApplication.style()
        style = self.style()

        ### Draw current value indicator
        if self._indicator != 0:
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)
            length = style.pixelMetric(QtWidgets.QStyle.PM_SliderLength, opt, self)
            available = style.pixelMetric(QtWidgets.QStyle.PM_SliderSpaceAvailable, opt, self)


            y_loc= QtWidgets.QStyle.sliderPositionFromValue(self.minimum(),
                    self.maximum(), self._indicator, self.height(), opt.upsideDown)


            # draw indicator first, so underneath max and min
            indicator_color = QtGui.QColor(0,0,0)
            if not self.alarm:
                indicator_color.setNamedColor(gui_styles.INDICATOR_COLOR)
            else:
                indicator_color.setNamedColor(gui_styles.ALARM_COLOR)

            x_begin = (self.width()-gui_styles.INDICATOR_WIDTH)/2

            painter.setBrush(indicator_color)
            pen_bak = copy.copy(painter.pen())
            painter.setPen(painter.pen().setWidth(0))
            painter.drawRect(x_begin,y_loc,gui_styles.INDICATOR_WIDTH,self.height()-y_loc)

            painter.setPen(pen_bak)

        for i, value in enumerate([self._high, self._low]):
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)
            # pdb.set_trace()
            # Only draw the groove for the first slider so it doesn't get drawn
            # on top of the existing ones every time
            if i == 0:
                opt.subControls = style.SC_SliderGroove | style.SC_SliderHandle
            else:
                #opt.subControls = QtWidgets.QStyle.SC_SliderHandle
                opt.subControls = style.SC_SliderHandle


            if self.tickPosition() != self.NoTicks:
                opt.subControls |= QtWidgets.QStyle.SC_SliderTickmarks

            if self.pressed_control:
                opt.activeSubControls = self.pressed_control
                opt.state |= QtWidgets.QStyle.State_Sunken
            else:
                opt.activeSubControls = self.hover_control

            # opt.rect.setX(-self.width()/2)
            opt.sliderPosition = value
            opt.sliderValue = value
            style.drawComplexControl(QtWidgets.QStyle.CC_Slider, opt, painter, self)

        # draw ticks
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        length = style.pixelMetric(QtWidgets.QStyle.PM_SliderLength, opt, self)
        available = style.pixelMetric(QtWidgets.QStyle.PM_SliderSpaceAvailable, opt, self)
        border_offset = 5
        available -= border_offset

        levels = np.linspace(self.minimum(), self.maximum(), 5)

        painter.setFont(mono_font)

        for v in levels:
            label_str = str(int(round(v)))
            # label_str = "{0:d}".format(v)
            rect = painter.drawText(QtCore.QRect(), QtCore.Qt.TextDontPrint, label_str)

            y_loc= QtWidgets.QStyle.sliderPositionFromValue(self.minimum(),
                    self.maximum(), v, available, opt.upsideDown)

            bottom=y_loc+length//2+rect.height()//2+(border_offset/2)-3
            # there is a 3 px offset that I can't attribute to any metric
            #left = (self.width())-(rect.width())-10
            left = (self.width()/2)-(gui_styles.INDICATOR_WIDTH/2)-rect.width()-3

            pos=QtCore.QPoint(left, bottom)
            painter.drawText(pos, label_str)

        self.setTickInterval(levels[1]-levels[0])




    def mousePressEvent(self, event):
        event.accept()

        style = QtWidgets.QApplication.style()
        button = event.button()

        # In a normal slider control, when the user clicks on a point in the
        # slider's total range, but not on the slider part of the control the
        # control would jump the slider value to where the user clicked.
        # For this control, clicks which are not direct hits will slide both
        # slider parts

        if button:
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)

            self.active_slider = -1

            for i, value in enumerate([self._low, self._high]):
                opt.sliderPosition = value
                hit = style.hitTestComplexControl(style.CC_Slider, opt, event.pos(), self)
                if hit == style.SC_SliderHandle:
                    self.active_slider = i
                    self.pressed_control = hit

                    self.triggerAction(self.SliderMove)
                    self.setRepeatAction(self.SliderNoAction)
                    self.setSliderDown(True)
                    break

            if self.active_slider < 0:
                self.pressed_control = QtWidgets.QStyle.SC_SliderHandle
                self.click_offset = self.__pixelPosToRangeValue(self.__pick(event.pos()))
                self.triggerAction(self.SliderMove)
                self.setRepeatAction(self.SliderNoAction)
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self.pressed_control != QtWidgets.QStyle.SC_SliderHandle:
            event.ignore()
            return

        event.accept()

        # get old values
        old_low = copy.copy(self._low)
        old_high = copy.copy(self._high)

        new_pos = self.__pixelPosToRangeValue(self.__pick(event.pos()))
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        if self.active_slider < 0:
            offset = new_pos - self.click_offset
            self._high += offset
            self._low += offset
            if self._low < self.minimum():
                diff = self.minimum() - self._low
                self._low += diff
                self._high += diff
            if self._high > self.maximum():
                diff = self.maximum() - self._high
                self._low += diff
                self._high += diff
        elif self.active_slider == 0:
            if new_pos >= self._high:
                #new_pos = self._high - 1
                new_pos = self._low
            self._low = new_pos
        else:
            if new_pos <= self._low:
                #new_pos = self._low + 1
                new_pos = self._high
            self._high = new_pos
        self.click_offset = new_pos
        self.update()
        self.emit(QtCore.SIGNAL('sliderMoved(int)'), new_pos)

        # emit valuechanged signal
        if (old_low != self._low) or (old_high != self._high):
            self.valueChanged.emit((self._low, self._high))

    def __pick(self, pt):
        if self.orientation() == QtCore.Qt.Horizontal:
            return pt.x()
        else:
            return pt.y()

    def __pixelPosToRangeValue(self, pos):
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        style = QtWidgets.QApplication.style()

        gr = style.subControlRect(style.CC_Slider, opt, style.SC_SliderGroove, self)
        sr = style.subControlRect(style.CC_Slider, opt, style.SC_SliderHandle, self)

        if self.orientation() == QtCore.Qt.Horizontal:
            slider_length = sr.width()
            slider_min = gr.x()
            slider_max = gr.right() - slider_length + 1
        else:
            slider_length = sr.height()
            slider_min = gr.y()
            slider_max = gr.bottom() - slider_length + 1
        return style.sliderValueFromPosition(self.minimum(), self.maximum(), pos - slider_min, slider_max - \
            slider_min, opt.upsideDown)


class Plot(pg.PlotWidget):

    limits_changed = QtCore.Signal(tuple)

    def __init__(self, name, buffer_size = 4092, plot_duration = 5, abs_range = None, safe_range = None, color=None):
        #super(Plot, self).__init__(axisItems={'bottom':TimeAxis(orientation='bottom')})
        # construct title html string
        titlestr = "<h1 style=\"{title_style}\">{title_text}</h1>".format(title_style=gui_styles.TITLE_STYLE,
                                                                      title_text=name)


        super(Plot, self).__init__(background=gui_styles.BACKGROUND_COLOR,
                                   title=titlestr)
        self.timestamps = deque(maxlen=buffer_size)
        self.history = deque(maxlen=buffer_size)
        # TODO: Make @property to update buffer_size, preserving history
        self.plot_duration = plot_duration



        self._start_time = time.time()
        self._last_time = time.time()
        self._last_relative_time = 0

        self.abs_range = None
        if abs_range:
            self.abs_range = abs_range
            self.setYRange(self.abs_range[0], self.abs_range[1])

        self.safe_range = (0,0)
        if safe_range:
            self.safe_range = safe_range


        self.setXRange(0, plot_duration)

        # split plot curve into two so that the endpoint doesn't get connected to the start point
        self.early_curve = self.plot(width=3)
        self.late_curve = self.plot(width=3)
        self.time_marker = self.plot()

        self.min_safe = pg.InfiniteLine(movable=True, angle=0, pos=self.safe_range[0])
        self.max_safe = pg.InfiniteLine(movable=True, angle=0, pos=self.safe_range[1])
        self.min_safe.sigPositionChanged.connect(self._safe_limits_changed)
        self.max_safe.sigPositionChanged.connect(self._safe_limits_changed)

        self.addItem(self.min_safe)
        self.addItem(self.max_safe)

        if color:
            self.early_curve.setPen(color=color, width=3)
            self.late_curve.setPen(color=color, width=3)


    def set_duration(self, dur):
        self.plot_duration = int(round(dur))
        self.setXRange(0, self.plot_duration)


    def update_value(self, new_value):
        """
        new_value: (timestamp from time.time(), value)
        """
        this_time = time.time()
        #time_diff = this_time-self._last_time
        limits = self.getPlotItem().viewRange()
        current_relative_time = (this_time-self._start_time) % self.plot_duration
        self.time_marker.setData([current_relative_time, current_relative_time],
                                 [limits[1][0], limits[1][1]])

        self.timestamps.append(new_value[0])
        self.history.append(new_value[1])

        # filter values based on timestamps
        ts_array = np.array(self.timestamps)
        end_ind = len(self.history)
        start_ind = np.where(ts_array > (this_time - self.plot_duration))[0][0]

        # subtract start time and take modulus of duration to get wrapped timestamps
        plot_timestamps = np.mod(ts_array[start_ind:end_ind]-self._start_time, self.plot_duration)
        plot_values = np.array([self.history[i] for i in range(start_ind, end_ind)])

        # find the point where the time resets
        try:
            reset_ind = np.where(np.diff(plot_timestamps)<0)[0][0]

            # plot early and late
            self.early_curve.setData(plot_timestamps[0:reset_ind+1],plot_values[0:reset_ind+1] )
            self.late_curve.setData(plot_timestamps[reset_ind+1:], plot_values[reset_ind+1:])

        except IndexError:
            self.early_curve.setData(plot_timestamps, plot_values)
            self.late_curve.clear()

        #self._last_time = this_time

    def _safe_limits_changed(self, val):
        # ignore input val, just emit the current value of the lines
        self.limits_changed.emit((self.min_safe.value(),
                                       self.max_safe.value()))

    @QtCore.Slot(tuple)
    def set_safe_limits(self, limits):
        self.max_safe.setPos(limits[1])
        self.min_safe.setPos(limits[0])

class QHLine(QtWidgets.QFrame):
    """
    with respct to https://stackoverflow.com/a/51057516
    """
    def __init__(self, parent=None, color=QtGui.QColor(gui_styles.DIVIDER_COLOR)):
        super(QHLine, self).__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Plain)
        self.setLineWidth(0)
        self.setMidLineWidth(3)
        self.setContentsMargins(0, 0, 0, 0)
        self.setColor(color)

    def setColor(self, color):
        pal = self.palette()
        pal.setColor(QtGui.QPalette.WindowText, color)
        self.setPalette(pal)

class TimeAxis(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLabel(text='Time', units=None)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%H:%M:%S') for value in values]


if __name__ == "__main__":
    # just for testing, should be run from main
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(gui_styles.GLOBAL)
    gui = Vent_Gui()
    sys.exit(app.exec_())





