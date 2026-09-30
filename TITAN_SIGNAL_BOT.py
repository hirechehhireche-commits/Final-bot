#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
  TITAN COMPATIBILITY ENTRYPOINT (بوابة التوافق العكسي التلقائي)
  ═════════════════════════════════════════════════════════════════════════════
  يضمن تشغيل البوت بسلاسة تامة إذا كان أمر التشغيل في Render أو السيرفر القديم
  مضبوطاً على: python TITAN_SIGNAL_BOT.py أو python TITAN_UNIFIED_BOT.py
═══════════════════════════════════════════════════════════════════════════════
"""
import sys, os, runpy

if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    runpy.run_module('TITAN_UNIFIED_BOT', run_name='__main__')
