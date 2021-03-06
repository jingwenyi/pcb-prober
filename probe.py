#!/usr/bin/env python3
#
# Copyright (C) 2020 Herbert Poetzl

import sys
import cv2
import numpy as np

import errno
import posix
import struct

import serial

from time import sleep, time
from random import randint

from threading import Thread, Condition, Lock


tty = sys.argv[1]
baud = int(sys.argv[2])

ser = serial.Serial(
    port = tty,
    baudrate = baud,
    bytesize = serial.EIGHTBITS,
    parity = serial.PARITY_NONE,
    stopbits = serial.STOPBITS_ONE,
    interCharTimeout = 0.5,
    timeout = 5.0,
    xonxoff = False,
    rtscts = False,
    dsrdtr = False);

# fifo = posix.open(sys.argv[1], posix.O_WRONLY | posix.O_NONBLOCK)

enable = True
active = True
exit = False
halt = False
quit = False

frame = None
frame_cnt = 0
frame_cnt_lock = Lock()
frame_cnt_cond = Condition(frame_cnt_lock)

frame_time = time()
frame_delta = 1
frame_fps = 1

analysis = None
analysis_cnt = 0

analysis_time = time()
analysis_delta = 1

ana_size = (720, 720)
ana_roi = (int((1920 - ana_size[0])/2),
           int((1080 - ana_size[1])/2),
           int((1920 - ana_size[0])/2) + ana_size[0],
           int((1080 - ana_size[1])/2) + ana_size[1])

ana_obj = [0]*4
ana_pos = [0]*4
ana_pas = [0]*4
ana_idx = -1
ana_seq = [0]*5

thr_val = [105, 125, 130, 115, 125]



cap = cv2.VideoCapture(0)

ini_con = cap.get(cv2.CAP_PROP_CONTRAST)
ini_bri = cap.get(cv2.CAP_PROP_BRIGHTNESS)
ini_sat = cap.get(cv2.CAP_PROP_SATURATION)

cap.set(cv2.CAP_PROP_FPS, 25)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

cap.set(cv2.CAP_PROP_CONTRAST, 0.10)
cap.set(cv2.CAP_PROP_BRIGHTNESS, 0.95)
cap.set(cv2.CAP_PROP_SATURATION, 0.15)


col = [(0,0,255), (0,200,255), (255,50,50), (0,200,0), (255,255,255), (0,0,0)]


def ovtext(img, txt="test", pos=(0,0), col=(255,255,255)):
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1

    # cv2.putText(img, txt, pos,
    #    font, font_scale, (0,0,0), 4, cv2.LINE_AA)
    cv2.putText(img, txt, pos,
        font, font_scale, col, 2, cv2.LINE_AA)


def overlay(img):
    ox, oy, ow, oh = 4, 4, 1920-8, 32

    sub = img[oy:oy+oh, ox:ox+ow]
    img[oy:oy+oh, ox:ox+ow] = sub >> 1

    rx0, ry0, rx1, ry1 = ana_roi
    cx, cy, r = int((rx0+rx1)/2), int((ry0+ry1)/2), 64
    
    cv2.rectangle(img, (rx0, ry0), (rx1, ry1), (0,0,255), 1)
    cv2.line(img, (cx, cy-r), (cx, cy+r), (0,0,0), 3)
    cv2.line(img, (cx-r, cy), (cx+r, cy), (0,0,0), 3)
    cv2.line(img, (cx, cy-r), (cx, cy+r), (0,255,0), 1)
    cv2.line(img, (cx-r, cy), (cx+r, cy), (0,255,0), 1)

    ovtext(img, "FPS %3.1f" % (frame_fps), (10, 30))
    ovtext(img, "*%08d" % (prev_frame_cnt), (240, 30))

    if enable:
        ovtext(img, "ENABLED", (480, 30))
    elif halt:
        ovtext(img, "HALTING", (10, 64))
    elif quit:
        ovtext(img, "EXITING", (10, 64))
    else:
        ovtext(img, "ACTIVE", (10, 64))

def overana(img):
    ox, oy, ow, oh = 4, 4, ana_roi[3]-8, 66

    sub = img[oy:oy+oh, ox:ox+ow]
    img[oy:oy+oh, ox:ox+ow] = sub >> 1

    cx, cy, r = int(ana_size[0]/2), int(ana_size[1]/2), 64

    cv2.line(img, (cx, cy-r), (cx, cy+r), (0,0,0), 3)
    cv2.line(img, (cx-r, cy), (cx+r, cy), (0,0,0), 3)
    cv2.line(img, (cx, cy-r), (cx, cy+r), (0,255,0), 1)
    cv2.line(img, (cx-r, cy), (cx+r, cy), (0,255,0), 1)

    # rx0, ry0, rx1, ry1 = caproi()
    
    # cv2.rectangle(img, (0, 0), (640, ry0), (0,0,0), -1)

    # cv2.line(img, (rx0, ry0), (rx0, ry1), (255,255,255), 1)

    lag = frame_cnt - analysis_cnt
    ovtext(img, "TIME %3.1fms" % (analysis_delta), (10, 30))
    ovtext(img, "*%08d" % (prev_analysis_cnt), (240, 30))
    ovtext(img, "LAG %d" % (lag), (480, 30))

    #ovtext(img, "STATE %s" % (state_str(state)), (10, 64))
    #ovtext(img, "+%3.1fs" % (sdelta()), (300, 64))

    ovtext(img, "%3d %3d %3d %3d %3d" % tuple(thr_val), (10, 64))

    if active:
        ovtext(img, "ACTIVE", (480, 64))

def choice(img):
    pass
    # rx0, ry0, rx1, ry1 = caproi()
    
    #    yp = ry0 + int((idx + 0.5)*row_size)
    #    cv2.circle(img, (selvis, yp), 10, col[idx], -1)
    #    cv2.circle(img, (selvis, yp), 15, col[4], 5)


def capture():
    global frame, frame_cnt, frame_cnt_cond
    global frame_time, frame_delta, frame_fps
    global cap, exit

    frame_time = time()
    fps = [0]*25

    while cap.isOpened():
        ret, new = cap.read()
        if ret:
            with frame_cnt_cond:
                frame = new
                frame_cnt += 1
                frame_cnt_cond.notify_all()

                prev = frame_time
                frame_time = time()
                frame_delta = frame_time - prev

                fps = [1/frame_delta] + fps[:-1]

                if frame_cnt % 10 == 0:
                    frame_fps = round(sum(fps))/25;
            
        if exit:
            break


def analyze():
    global frame, frame_cnt, frame_cnt_cond
    global analysis, analysis_cnt
    global analysis_time, analysis_delta
    global align, finish, exit
    global ana_obj, ana_pos, ana_pas
    global ana_idx, ana_seq

    global thr_val

    this = None
    this_cnt = 0

    rx0, ry0, rx1, ry1 = ana_roi
    #hsv_grid = [np.array([0,0,30]), np.array([200,50,160])]
    #hsv_high = [np.array([0,40,0]), np.array([72,255,255])]
    kern_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
    kern_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))

    par = cv2.SimpleBlobDetector_Params()
    par.minThreshold = 50
    par.maxThreshold = 260

    par.filterByArea = True
    par.minArea = 8000
    par.maxArea = 20000

    par.filterByColor = False

    par.filterByCircularity = False
    par.minCircularity = 0.2

    par.filterByConvexity = True
    par.minConvexity = 0.8

    par.filterByInertia = False
    par.minInertiaRatio = 0.5

    detector = cv2.SimpleBlobDetector_create(par)

    while not exit:
        with frame_cnt_cond:
            while frame_cnt == this_cnt:
                frame_cnt_cond.wait()
            this = frame.copy()
            this_cnt = frame_cnt

        mark = time()

        roi = this[ry0:ry1, rx0:rx1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        #msk_grid = cv2.inRange(hsv, hsv_grid[0], hsv_grid[1]) 
        #msk_high = cv2.inRange(hsv, hsv_high[0], hsv_high[1]) 
        #msk = cv2.bitwise_not(cv2.bitwise_or(msk_grid, msk_high)) 
        #res = cv2.bitwise_and(roi, roi, mask=msk)
        h, s, v = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]
        ret, ht = cv2.threshold(h, thr_val[0], 0, cv2.THRESH_TOZERO)
        ret, ht = cv2.threshold(ht, thr_val[1], 0, cv2.THRESH_TOZERO_INV)
        ret, st = cv2.threshold(s, thr_val[2], 255, cv2.THRESH_BINARY)
        ret, vt = cv2.threshold(v, thr_val[3], 255, cv2.THRESH_BINARY)
        thr = cv2.merge((ht,st,vt))
        #ret, thr = cv2.threshold(s, 80, 250, cv2.THRESH_TOZERO)
        # gry = cv2.cvtColor(thr, cv2.COLOR_BGR2GRAY)
        mor = cv2.morphologyEx(thr, cv2.MORPH_OPEN, kern_open)
        img = cv2.morphologyEx(mor, cv2.MORPH_CLOSE, kern_close)
        #img = cv2.cvtColor(mor, cv2.COLOR_GRAY2RGB)
        #img = thr

        kpt = detector.detect(img)
        img = cv2.drawKeypoints(img, kpt, np.array([]), \
            (255,255,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

        #split = align - rx0
        #limit = finish - rx0
        #purge = ignore - rx0

        pos = [0]*len(kpt)

        for idx, kp in enumerate(kpt):
            xf, yf = kp.pt
            x, y = int(round(xf)), int(round(yf))

            pos[idx] = (x, y)

            if kp.size < thr_val[4]:
                ovtext(img, "%3d" % kp.size, (x-30, y-8), (0,0,0))
            else:
                ovtext(img, "%3d" % kp.size, (x-30, y-8), (255,255,255))

        #    if x < split:
        #        obj[i] += 1
        #        if x > limit and x < purge and pos[i] < x:
        #            pos[i] = x
        #        cv2.circle(img, (x, y), 15, col[i], -1)
        #    else:
        #        x -= split
        #        if pas[i] < x:
        #            pas[i] = x

        #ana_obj = obj[0:4].copy()
        #ana_pos = pos[0:4].copy()
        #ana_pas = pas[0:4].copy()

        #max_val = max(ana_pos)
        #max_idx = ana_pos.index(max_val)

        #if max_val > 0:
        #    seq = ana_seq
        #    seq = [max_idx] + seq[:-1]
        #    idx = max(seq, key=seq.count)
        #    ana_idx = idx
        #    ana_seq = seq
        #else:
        #    ana_idx = -1

        #this[ry0:ry1, rx0:rx1] = img

        analysis = img
        analysis_cnt += 1

        prev = analysis_time
        analysis_time = time()
        analysis_delta = (analysis_time - mark)*1000


def ender():
    global ser, exit
    init = True

    while not exit:
        if init:
            while ser.in_waiting > 0:
                res = ser.readline()
                init = False
                print("SER:", res)
    
        elif ser.in_waiting > 0:
            res = ser.readline()
            print("N:", res)

        else:
            print("X")

        sleep(0.05)


def engine():
    global timer, exit

    while not exit:
        sleep(0.05)




win_flags = cv2.WINDOW_AUTOSIZE | cv2.WINDOW_GUI_NORMAL

cv2.namedWindow('Capture', win_flags)
cv2.resizeWindow('Capture', 1920, 1080)
cv2.moveWindow('Capture', 900, 64) 
# cv2.setMouseCallback("Capture", mouse_event)

capture_thread = Thread(target=capture)
capture_thread.start()

cv2.namedWindow('Analyze', win_flags)
cv2.resizeWindow('Analyze', ana_size[0], ana_size[1])
cv2.moveWindow('Analyze', 900, 1200) 

analyze_thread = Thread(target=analyze)
analyze_thread.start()

ender_thread = Thread(target=ender)
ender_thread.start()

engine_thread = Thread(target=engine)
engine_thread.start()


try:
    prev_frame_cnt = 0
    prev_analysis_cnt = 0

    while not exit:
        if prev_frame_cnt != frame_cnt:
            img = frame.copy()
            prev_frame_cnt = frame_cnt

            overlay(img)


            #cseq = [str(_) for _ in ana_seq]
            #ovtext(img, " " + ".".join(cseq), (240, 64))
            #cobj = [str(min(9,_)) for _ in ana_obj]
            #ovtext(img, ".".join(cobj), (480, 64))

            cv2.imshow('Capture', img)

        if prev_analysis_cnt != analysis_cnt:
            img = analysis
            prev_analysis_cnt = analysis_cnt

            overana(img)
            #choice(img)


            cv2.imshow('Analyze', img)

            # print(ana_obj, ana_pos, ana_pas)

        key = cv2.waitKey(1) & 0xFF

        if key == 27:           # escape
            exit = True

        elif key == ord('c'):   # continue
            halt = False
        elif key == ord('d'):   # disable
            enable = False
        elif key == ord('e'):   # enable
            enable = True
        elif key == ord('h'):   # halt
            halt = True
        elif key == ord('q'):   # quit
            quit = True

        elif key == ord('1'):   # thr[0]--
            thr_val[0] -= 1
        elif key == ord('2'):   # thr[0]++
            thr_val[0] += 1
        elif key == ord('3'):   # thr[1]--
            thr_val[1] -= 1
        elif key == ord('4'):   # thr[1]++
            thr_val[1] += 1
        elif key == ord('5'):   # thr[2]--
            thr_val[2] -= 1
        elif key == ord('6'):   # thr[2]++
            thr_val[2] += 1
        elif key == ord('7'):   # thr[3]--
            thr_val[3] -= 1
        elif key == ord('8'):   # thr[3]++
            thr_val[3] += 1

        elif key == 255:        # nokey
            pass

        else:
            print("unknown key %d" % key)


        """
        elif key == ord('0'):   # reset
            cap.set(cv2.CAP_PROP_CONTRAST, ini_con)
            cap.set(cv2.CAP_PROP_BRIGHTNESS, ini_bri)
            cap.set(cv2.CAP_PROP_SATURATION, ini_sat)

        elif key == ord('1'):   # dec contrast
            val = cap.get(cv2.CAP_PROP_CONTRAST)
            cap.set(cv2.CAP_PROP_CONTRAST, val - 0.01)
        elif key == ord('2'):   # inc contrast
            val = cap.get(cv2.CAP_PROP_CONTRAST)
            cap.set(cv2.CAP_PROP_CONTRAST, val + 0.01)

        elif key == ord('3'):   # dec brightness
            val = cap.get(cv2.CAP_PROP_BRIGHTNESS)
            cap.set(cv2.CAP_PROP_BRIGHTNESS, val - 0.01)
        elif key == ord('4'):   # inc brightness
            val = cap.get(cv2.CAP_PROP_BRIGHTNESS)
            cap.set(cv2.CAP_PROP_BRIGHTNESS, val + 0.01)

        elif key == ord('5'):   # dec saturation
            val = cap.get(cv2.CAP_PROP_SATURATION)
            cap.set(cv2.CAP_PROP_SATURATION, val - 0.01)
        elif key == ord('6'):   # inc saturation
            val = cap.get(cv2.CAP_PROP_SATURATION)
            cap.set(cv2.CAP_PROP_SATURATION, val + 0.01)
        """

except KeyboardInterrupt:
    exit = True

capture_thread.join()
analyze_thread.join()
ender_thread.join()
engine_thread.join()

cap.release()
cv2.destroyAllWindows()

