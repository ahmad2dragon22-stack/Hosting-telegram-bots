# Hosting-telegram-bots

هذا المشروع هو مدير لاستضافة وتشغيل ملفات بوتات تيليجرام بصيغة Python على الخادم.

ميزات مضافة:
- دعم تحميل ملفات متعددة لكل بوت (نسخ/إصدارات).
- تخزين كل بوت في مجلد مخصص داخل `hosted_bots/`.
- أوامر إدارة: `/files`, `/config`, `/set`, `/startbot`, `/stopbot`, `/restartbot`, `/removefile`, `/dashboard`.
- إعدادات per-bot: `enabled`, `auto_restart`, `main` (مسار الملف الرئيسي).

كيفية الاستخدام السريع:
- ارسل ملف `.py` إلى البوت مع caption مثل `bot:mybot` لتعيين اسم البوت.
- إن لم تحدد اسم البوت، سيُستخدم اسم الملف بدون امتداد.
- لعرض الملفات لبوت: `/files mybot`
- لعرض إعدادات بوت: `/config mybot`
- لتعديل إعداد: `/set mybot auto_restart false`
- لتشغيل/إيقاف/إعادة تشغيل: `/startbot mybot`, `/stopbot mybot`, `/restartbot mybot`
- لحذف ملف محدد: `/removefile mybot <file_id_or_index>`

تحديثات أخرى ممكنة (أفكار مستقبلية):
- واجهة ويب مبسطة لإدارة البوتات.
- نظام صلاحيات متعدد للمستخدمين.
- نسخ احتياطي و استعادة إعدادات/ملفات البوتات.
- دعم حاويات (Docker) لكل بوت لعزل التنفيذ.

تثبيت المتطلبات:
```bash
pip install -r requirements.txt
```

تشغيل:
```bash
python main.py
```