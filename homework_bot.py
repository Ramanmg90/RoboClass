"""ربات مدیریت تکالیف - Telegram"""
import os,sqlite3,logging,html,io,re,random
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Spacer,Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from telegram import Update,InlineKeyboardButton as Btn,InlineKeyboardMarkup as Markup,ReplyKeyboardMarkup as RKM,ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application,CommandHandler,MessageHandler,CallbackQueryHandler,ContextTypes,filters

logging.basicConfig(level=logging.INFO)
def _load_env():
    """متغیرها را از فایل .env کنار ربات می‌خواند (این فایل روی گیت‌هاب نمی‌رود)"""
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),".env")
    if not os.path.exists(p):return
    with open(p,encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1);os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
_load_env()
TOKEN = os.environ.get("BOT_TOKEN","")
TEACHERS = {int(x) for x in os.environ.get("TEACHER_IDS","").replace(" ","").split(",") if x.isdigit()}
TZ = ZoneInfo("Asia/Tehran")
HTML = ParseMode.HTML
STICKERS=[]  # file_id استیکرها را اینجا بگذار؛ با فرستادن استیکر به ربات (از حساب معلم) file_id را می‌گیری

CLASS_NAMES=["المنتری 2 پسران","المنتری 1 دختران","بیسیک 3 پسران","بیسیک 3 دختران","بیسیک 2 دختران","بیسیک 2 پسران"]

def pick(*o):return random.choice(o)

# ---------- دکمه‌های کیبورد ----------
BTN_MY="📚 تکلیف‌های من";BTN_SEND="📤 ارسال تکلیف"
BTN_CLS="📚 کلاس‌ها";BTN_STU="👥 دانش‌آموزان";BTN_ASG="📋 تکالیف";BTN_REP="📊 گزارش"
BTN_OK="✅ تایید";BTN_RETRY="✏️ عوض کردن"
CLOSE=[Btn("✖️ بستن",callback_data="p:home")]

def kb_student():return RKM([[BTN_MY,BTN_SEND]],resize_keyboard=True)
def kb_teacher():return RKM([[BTN_CLS,BTN_STU],[BTN_ASG,BTN_REP]],resize_keyboard=True)
def kb_confirm():return RKM([[BTN_OK,BTN_RETRY]],resize_keyboard=True)
def kb_classes():
    names=[c["name"] for c in db("SELECT * FROM classes ORDER BY id")]
    return RKM([names[i:i+2] for i in range(0,len(names),2)],resize_keyboard=True)

# ---------- صفحه‌های لیستی پنل معلم (هم از کیبورد، هم از دکمه‌های شیشه‌ای بازگشت) ----------
def v_classes():
    rows=db("SELECT * FROM classes ORDER BY id")
    kb=[[Btn(r["name"],callback_data=f"cl:{r['id']}")] for r in rows];kb.append(CLOSE)
    return "📚 کلاس‌ها:",kb
def v_students():
    rows=db("SELECT * FROM students ORDER BY name")
    kb=[[Btn(r["name"],callback_data=f"st:{r['user_id']}")] for r in rows];kb.append(CLOSE)
    return f"👥 دانش‌آموزان ({len(rows)}):",kb
def v_asgn():
    rows=db("SELECT * FROM assignments ORDER BY id DESC LIMIT 10")
    kb=[[Btn(f"{r['title'][:20]} ({shamsi(r['start_time'])})",callback_data=f"as:{r['id']}")] for r in rows]
    kb.append([Btn("➕ تکلیف جدید",callback_data="as_new")]);kb.append(CLOSE)
    return "📋 تکالیف:",kb
def v_report():
    classes=db("SELECT * FROM classes ORDER BY id")
    kb=[[Btn(c["name"],callback_data=f"rep:{c['id']}")] for c in classes];kb.append(CLOSE)
    return "گزارش کدام کلاس؟",kb
TEACHER_VIEWS={BTN_CLS:v_classes,BTN_STU:v_students,BTN_ASG:v_asgn,BTN_REP:v_report}
async def sticker(bot,chat_id):
    if STICKERS:
        try:await bot.send_sticker(chat_id,random.choice(STICKERS))
        except Exception as ex:logging.warning(f"sticker failed: {ex}")

def g2j(gy,gm,gd):
    g_d_m=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400+gd+g_d_m[gm-1]
    jy=-1595+33*(days//12053);days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:jy+=(days-1)//365;days=(days-1)%365
    jm,jd=(1+days//31,1+days%31)if days<186 else(7+(days-186)//30,1+(days-186)%30)
    return jy,jm,jd

def shamsi(s,with_time=True):
    if not s:return ""
    try:dt=datetime.strptime(s[:16],"%Y-%m-%d %H:%M")
    except:
        try:dt=datetime.strptime(s[:10],"%Y-%m-%d");with_time=False
        except:return str(s)[:10]
    jy,jm,jd=g2j(dt.year,dt.month,dt.day)
    out=f"{jy}/{jm:02d}/{jd:02d}"
    if with_time:out+=f" - {dt:%H:%M}"
    return out.translate(str.maketrans("0123456789","۰۱۲۳۴۵۶۷۸۹"))

def now_str():return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
def e(x):return html.escape(str(x or ""))
MONTHS=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
def fa(x):return str(x).translate(str.maketrans("0123456789","۰۱۲۳۴۵۶۷۸۹"))
def j2g(jy,jm,jd):
    jy+=1595
    days=-355668+(365*jy)+((jy//33)*8)+(((jy%33)+3)//4)+jd+((jm-1)*31 if jm<7 else ((jm-7)*30)+186)
    gy=400*(days//146097);days%=146097
    if days>36524:
        days-=1;gy+=100*(days//36524);days%=36524
        if days>=365:days+=1
    gy+=4*(days//1461);days%=1461
    if days>365:gy+=(days-1)//365;days=(days-1)%365
    gd=days+1
    sal=[0,31,29 if(gy%4==0 and gy%100!=0)or gy%400==0 else 28,31,30,31,30,31,31,30,31,30,31]
    gm=0
    while gm<13 and gd>sal[gm]:gd-=sal[gm];gm+=1
    return gy,gm,gd
def jnow():n=datetime.now(TZ);return g2j(n.year,n.month,n.day)
def jleap(y):return g2j(*j2g(y,12,30))==(y,12,30)
def jdays(y,m):return 31 if m<=6 else 30 if m<=11 else(30 if jleap(y)else 29)
def j2s(y,m,d,h,i):
    gy,gm,gd=j2g(y,m,d);return f"{gy:04d}-{gm:02d}-{gd:02d} {h:02d}:{i:02d}"
def is_teacher(uid):return uid in TEACHERS
def db(q,a=(),one=False,write=False):
    con=sqlite3.connect("homework.db");con.row_factory=sqlite3.Row
    cur=con.execute(q,a)
    if write:con.commit();res=cur.lastrowid;con.close();return res
    res=cur.fetchone()if one else cur.fetchall();con.close();return res

def init_db():
    db("CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY,name TEXT)",write=True)
    db("CREATE TABLE IF NOT EXISTS students(user_id INTEGER PRIMARY KEY,name TEXT,class_id INTEGER,username TEXT)",write=True)
    db("CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,class_id INTEGER,title TEXT,description TEXT,start_time TEXT,end_time TEXT,created_by INTEGER,created_at TEXT)",write=True)
    db("CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,assignment_id INTEGER,user_id INTEGER,created_at TEXT,sent_at TEXT,status TEXT DEFAULT 'open')",write=True)
    db("CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER,file_id TEXT,kind TEXT)",write=True)
    for i,name in enumerate(CLASS_NAMES,1):
        if db("SELECT 1 FROM classes WHERE id=?",(i,),one=True):
            db("UPDATE classes SET name=? WHERE id=? AND name=?",(name,i,f"سطح {i}"),write=True)
        else:
            db("INSERT INTO classes(id,name)VALUES(?,?)",(i,name),write=True)

def in_time_window(asgn):
    now=datetime.now(TZ)
    try:
        start=datetime.strptime(asgn["start_time"],"%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        end=datetime.strptime(asgn["end_time"],"%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        return start<=now<=end
    except:return False

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id;ctx.user_data.clear()
    if is_teacher(uid):await update.message.reply_text(pick("سلام معلم گرامی، وقت بخیر 🌷\nبرای مدیریت تکالیف از دکمه‌های پایین استفاده کنید 👇","سلام و خسته نباشید 🌿\nپنل مدیریت آماده است 👇","درود، خوش آمدید 👋\nبرای مدیریت تکالیف از دکمه‌های پایین استفاده کنید"),reply_markup=kb_teacher());return
    st=db("SELECT * FROM students WHERE user_id=?",(uid,),one=True)
    if st:
        await update.message.reply_text(pick("سلام، خوش برگشتید 🌸","سلام و وقت بخیر 👋 خوشحالیم که دوباره اینجایید","درود 🌟 خوش آمدید"),reply_markup=kb_student())
        await show_student_menu(ctx,update.effective_chat.id,uid)
    else:
        ctx.user_data["reg"]={};ctx.user_data["step"]="name"
        await update.message.reply_text(pick("سلام، خوش آمدید 🌸\nلطفاً نام و نام خانوادگی‌تان را بنویسید:","سلام و وقت بخیر 👋\nبرای شروع، نام و نام خانوادگی‌تان را بفرستید:","درود، به ربات تکالیف خوش آمدید 🌟\nلطفاً نام و نام خانوادگی‌تان را وارد کنید:"),reply_markup=ReplyKeyboardRemove())

async def on_text(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid,chat_id,text=update.effective_user.id,update.effective_chat.id,update.message.text.strip()
    step=ctx.user_data.get("step")
    if step=="name":
        ctx.user_data["reg"]["name"]=text;ctx.user_data["step"]="class"
        await update.message.reply_text(pick("ممنون 🌸 حالا لطفاً کلاس خود را انتخاب کنید 👇","خیلی خوب ✨ کلاس خودتان را از دکمه‌های پایین انتخاب کنید","نام شما ثبت شد 🌟 لطفاً کلاستان را مشخص کنید 👇"),reply_markup=kb_classes())
    elif step=="class":
        c=db("SELECT * FROM classes WHERE name=?",(text,),one=True)
        if not c:await update.message.reply_text(pick("لطفاً یکی از کلاس‌های کیبورد را انتخاب کنید 🌸","برای ادامه، کلاس خود را از دکمه‌های پایین انتخاب کنید 👇"),reply_markup=kb_classes());return
        ctx.user_data["reg"]["class_id"]=c["id"];ctx.user_data["step"]="confirm"
        await update.message.reply_text(f"👤 {e(ctx.user_data['reg']['name'])}\n🎓 کلاس: {e(c['name'])}\n\nاطلاعات بالا درست است؟ 🌸",reply_markup=kb_confirm(),parse_mode=HTML)
    elif step=="confirm":
        if text==BTN_OK:
            r=ctx.user_data.pop("reg")
            db("INSERT OR REPLACE INTO students(user_id,name,class_id,username)VALUES(?,?,?,?)",(uid,r["name"],r["class_id"],update.effective_user.username),write=True)
            ctx.user_data.pop("step",None)
            await update.message.reply_text(pick("✅ ثبت‌نام شما با موفقیت انجام شد 🌟 خوش آمدید!","تبریک 🎉 ثبت‌نام شما کامل شد. خوش آمدید 🌸","ثبت‌نام انجام شد ✨ از همراهی شما خوشحالیم 💙"),reply_markup=kb_student())
            await sticker(ctx.bot,chat_id);await show_student_menu(ctx,chat_id,uid)
        elif text==BTN_RETRY:
            ctx.user_data["step"]="class"
            await update.message.reply_text(pick("بسیار خوب، دوباره کلاس خود را انتخاب کنید 🔄","اشکالی ندارد 🌿 لطفاً یک بار دیگر کلاس خود را انتخاب کنید:"),reply_markup=kb_classes())
        else:await update.message.reply_text("لطفاً یکی از دکمه‌های پایین را بزنید 🌸",reply_markup=kb_confirm())
    elif is_teacher(uid)and text in TEACHER_VIEWS:
        for k in("step","edit_field","edit_aid","new_asgn","dt"):ctx.user_data.pop(k,None)
        t,kb=TEACHER_VIEWS[text]();await update.message.reply_text(t,reply_markup=Markup(kb),parse_mode=HTML)
    elif is_teacher(uid)and step in("as_title","as_desc"):
        na=ctx.user_data.setdefault("new_asgn",{})
        if "class_id" not in na:ctx.user_data.pop("step",None);await update.message.reply_text("مرحله گم شد. دوباره از «📋 تکالیف» شروع کنید.");return
        if step=="as_title":
            na["title"]=text;ctx.user_data["step"]="as_desc"
            await update.message.reply_text(pick("📝 لطفاً توضیحات تکلیف را بنویسید (در صورت نداشتن، علامت - را بفرستید):","✏️ توضیحات تکلیف چیست؟ (اگر ندارد، - بفرستید)"))
        else:
            na["description"]="" if text=="-" else text;ctx.user_data["step"]="as_dur"
            kb=[[Btn(f"{fa(n)} روز",callback_data=f"as_dur:{n}") for n in range(1,6)],[Btn("⚙️ غیره (تنظیم دستی)",callback_data="as_dur:0")]]
            await update.message.reply_text(pick("⏳ مهلت تحویل چقدر باشد؟\n(تکلیف از همین الان شروع می‌شود)","⏰ چند روز برای تحویل در نظر بگیریم؟\n(تکلیف از همین الان فعال می‌شود)"),reply_markup=Markup(kb))
    elif is_teacher(uid)and ctx.user_data.get("edit_field"):
        fld=ctx.user_data.pop("edit_field");aid=ctx.user_data.pop("edit_aid")
        db(f"UPDATE assignments SET {fld}=? WHERE id=?",(text,aid),write=True)
        ctx.user_data.pop("step",None);await update.message.reply_text(pick("✅ با موفقیت ذخیره شد.","انجام شد 🌿 تغییرات ذخیره شد.","✨ ذخیره شد."))
    elif text==BTN_MY:
        if not db("SELECT 1 FROM students WHERE user_id=?",(uid,),one=True):await update.message.reply_text(pick("لطفاً ابتدا ثبت‌نام کنید 🌸 برای شروع /start را بزنید","برای استفاده از ربات، ابتدا /start را بزنید 🙏"));return
        await show_student_menu(ctx,chat_id,uid)
    elif text==BTN_SEND:
        sess=db("SELECT * FROM sessions WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(uid,),one=True)
        if not sess:await update.message.reply_text(pick("لطفاً ابتدا یک تکلیف را از «📚 تکلیف‌های من» انتخاب کنید","ابتدا از «📚 تکلیف‌های من» تکلیف مورد نظر را انتخاب کنید 🌸"));return
        res=await do_send(ctx.bot,sess["id"],uid)
        await update.message.reply_text(send_ok() if res=="ok" else send_err(res))
        if res=="ok":await sticker(ctx.bot,chat_id)
    else:await update.message.reply_text(pick("برای شروع، لطفاً /start را بزنید 🌸","متوجه نشدم 🙏 لطفاً با /start شروع کنید","برای شروع دوباره /start را ارسال کنید 👋"))

async def show_student_menu(ctx,chat_id,uid):
    st=db("SELECT * FROM students WHERE user_id=?",(uid,),one=True)
    if not st:return
    asgns=db("SELECT * FROM assignments WHERE class_id=? ORDER BY id DESC LIMIT 5",(st["class_id"],))
    kb=[]
    for a in asgns:
        status="🔓"if in_time_window(a)else "🔒"
        kb.append([Btn(f"{status} {a['title']}",callback_data=f"a:{a['id']}")])
    if kb:await ctx.bot.send_message(chat_id,pick("📚 تکلیف‌های شما:\n(🔓 باز | 🔒 بسته)","📖 این هم تکلیف‌های اخیر شما 🌸\n🔓 باز | 🔒 بسته","✨ لطفاً تکلیف مورد نظر را انتخاب کنید:\n🔓 باز | 🔒 بسته"),reply_markup=Markup(kb))
    else:await ctx.bot.send_message(chat_id,pick("فعلاً تکلیفی برای شما ثبت نشده است 🌿","در حال حاضر تکلیف جدیدی ندارید 🌸 خسته نباشید!"))

def send_ok():return pick("🚀 تکلیف شما برای معلم ارسال شد. خسته نباشید 🌸","✅ ارسال با موفقیت انجام شد. سپاس از شما 🌟","تکلیف شما تحویل داده شد 📬 موفق باشید ✨")
def send_err(res):
    if res=="empty":return pick("هنوز فایلی ارسال نکرده‌اید 🙏 لطفاً ابتدا عکس یا فایل بفرستید","فایلی دریافت نشده است 🌿 ابتدا تکلیف را ارسال کنید")
    return pick("این تکلیف پیش‌تر ارسال شده است ✅","قبلاً ارسال شده است 🌿 نیازی به ارسال دوباره نیست")

async def do_send(bot,sid,uid):
    sess=db("SELECT se.*,a.id aid,st.name,st.username,c.name cname FROM sessions se JOIN assignments a ON a.id=se.assignment_id JOIN students st ON st.user_id=se.user_id LEFT JOIN classes c ON c.id=st.class_id WHERE se.id=? AND se.user_id=? AND se.status='open'",(sid,uid),one=True)
    if not sess:return "none"
    files=db("SELECT * FROM files WHERE session_id=?",(sid,))
    if not files:return "empty"
    db("UPDATE sessions SET status='sent',sent_at=? WHERE id=?",(now_str(),sid),write=True)
    sess=db("SELECT se.*,a.id aid,st.name,st.username,c.name cname FROM sessions se JOIN assignments a ON a.id=se.assignment_id JOIN students st ON st.user_id=se.user_id LEFT JOIN classes c ON c.id=st.class_id WHERE se.id=?",(sid,),one=True)
    asgn=db("SELECT title FROM assignments WHERE id=?",(sess["aid"],),one=True)
    for tid in TEACHERS:
        try:
            msg=f"{pick('📥 تکلیف جدیدی دریافت شد','🔔 یک دانش‌آموز تکلیف خود را ارسال کرد','📬 تکلیف جدید دریافت شد')}\n👤 {e(sess['name'])}\n📚 تکلیف: {e(asgn['title'])}\n🕒 {shamsi(sess['sent_at'])}\n"
            if sess["username"]:msg+=f"🆔 @{e(sess['username'])}\n"
            msg+=f"🎓 کلاس: {e(sess['cname'])}\n📎 {len(files)} فایل"
            await bot.send_message(tid,msg,parse_mode=HTML)
            for f in files:
                if f["kind"]=="photo":await bot.send_photo(tid,f["file_id"],caption=e(sess["name"]))
                else:await bot.send_document(tid,f["file_id"],caption=e(sess["name"]))
        except Exception as ex:logging.warning(f"send to teacher failed: {ex}")
    return "ok"

async def on_cb(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q,d,uid,chat_id=update.callback_query,update.callback_query.data,update.callback_query.from_user.id,update.callback_query.message.chat_id
    await q.answer()
    if d.startswith("a:"):
        aid=int(d.split(":")[1]);asgn=db("SELECT * FROM assignments WHERE id=?",(aid,),one=True)
        st=db("SELECT * FROM students WHERE user_id=?",(uid,),one=True)
        if not st:await q.message.reply_text(pick("لطفاً ابتدا ثبت‌نام کنید 🌸 برای شروع /start را بزنید","برای استفاده از ربات، ابتدا /start را بزنید 🙏"));return
        if not in_time_window(asgn):await q.answer(pick("⏰ بازه زمانی این تکلیف به پایان رسیده یا هنوز شروع نشده است","🙏 در حال حاضر امکان ارسال برای این تکلیف وجود ندارد؛ بازه آن بسته است ⏳"),show_alert=True);return
        sess=db("SELECT * FROM sessions WHERE assignment_id=? AND user_id=? AND status='open'",(aid,uid),one=True)
        if not sess:sid=db("INSERT INTO sessions(assignment_id,user_id,created_at)VALUES(?,?,?)",(aid,uid,now_str()),write=True)
        else:sid=sess["id"]
        n=db("SELECT COUNT(*) c FROM files WHERE session_id=?",(sid,),one=True)["c"]
        await show(q,f"📚 {e(asgn['title'])}\n{e(asgn['description'])}\n\n{pick('لطفاً عکس یا فایل تکلیف را ارسال کنید 📸','تکلیف خود را به صورت عکس یا فایل بفرستید 📎','منتظر دریافت تکلیف شما هستیم 🌸')}\n📦 تعداد فایل‌های دریافتی: {fa(n)}\n\nپس از ارسال همه فایل‌ها، دکمه «📤 ارسال تکلیف» را از کیبورد پایین بزنید 👇")
    elif d.startswith("done:"):
        sid=int(d.split(":")[1]);n=db("SELECT COUNT(*) c FROM files WHERE session_id=?",(sid,),one=True)["c"]
        if n==0:await q.answer(pick("هنوز فایلی ارسال نکرده‌اید 🙏 لطفاً ابتدا عکس یا فایل بفرستید","فایلی دریافت نشده است 🌿 ابتدا تکلیف را ارسال کنید"),show_alert=True);return
        await show(q,pick(f"{fa(n)} فایل آماده ارسال است 📦 برای معلم ارسال شود؟",f"✨ {fa(n)} فایل دریافت شد. ارسال شود؟"),[[Btn("✅ ارسال",callback_data=f"send:{sid}"),Btn("بیشتر",callback_data=f"more:{sid}")]])
    elif d.startswith("more:"):
        sid=int(d.split(":")[1]);await show(q,pick("بسیار خوب، فایل بعدی را بفرستید 📎","لطفاً فایل بعدی را ارسال کنید 🌸"))
    elif d.startswith("send:"):
        res=await do_send(ctx.bot,int(d.split(":")[1]),uid)
        if res!="ok":await q.answer(send_err(res),show_alert=True);return
        await show(q,send_ok());await sticker(ctx.bot,chat_id)
    elif not is_teacher(uid):return
    elif d=="p:home":
        try:await q.message.delete()
        except Exception:pass
    elif d=="p:classes":
        t,kb=v_classes();await show(q,t,kb)
    elif d.startswith("cl:"):
        cid=int(d.split(":")[1]);c=db("SELECT * FROM classes WHERE id=?",(cid,),one=True)
        n=db("SELECT COUNT(*) c FROM students WHERE class_id=?",(cid,),one=True)["c"]
        kb=[[Btn("✏️ نام را عوض کن",callback_data=f"cl_edit:{cid}")],[Btn("⬅️ بازگشت",callback_data="p:classes")]]
        await show(q,f"🎓 {e(c['name'])}\n👥 دانش‌آموزان: {n}",kb)
    elif d.startswith("cl_edit:"):
        cid=int(d.split(":")[1]);ctx.user_data["edit_field"]="name";ctx.user_data["edit_aid"]=cid;ctx.user_data["step"]="edit"
        await show(q,"نام جدید را بنویس:")
    elif d=="p:students":
        t,kb=v_students();await show(q,t,kb)
    elif d.startswith("st:"):
        uid2=int(d.split(":")[1]);st=db("SELECT * FROM students WHERE user_id=?",(uid2,),one=True)
        c=db("SELECT * FROM classes WHERE id=?",(st["class_id"],),one=True)
        n=db("SELECT COUNT(*) c FROM sessions WHERE user_id=? AND status='sent'",(uid2,),one=True)["c"]
        un=f"@{e(st['username'])}"if st["username"]else "ندارد"
        kb=[[Btn("📂 تکالیف",callback_data=f"st_asgn:{uid2}"),Btn("🗑 حذف",callback_data=f"st_del:{uid2}")],[Btn("⬅️ بازگشت",callback_data="p:students")]]
        await show(q,f"👤 {e(st['name'])}\n🎓 کلاس: {e(c['name'])}\n🆔 {un}\n📦 جلسات: {n}",kb)
    elif d.startswith("st_asgn:"):
        uid2=int(d.split(":")[1])
        rows=db("SELECT se.id,se.sent_at,a.title FROM sessions se JOIN assignments a ON a.id=se.assignment_id WHERE se.user_id=? AND se.status='sent' ORDER BY se.id DESC",(uid2,))
        kb=[[Btn(f"{shamsi(r['sent_at'])} - {e(r['title'][:20])}",callback_data=f"st_files:{r['id']}")] for r in rows]
        kb.append([Btn("⬅️ بازگشت",callback_data=f"st:{uid2}")])
        await show(q,"📂 تکالیف ارسالی:",kb)
    elif d.startswith("st_files:"):
        sid=int(d.split(":")[1]);await send_session(ctx.bot,chat_id,sid)
    elif d.startswith("st_del:"):
        uid2=int(d.split(":")[1])
        kb=[[Btn("✅ بله",callback_data=f"st_del_ok:{uid2}"),Btn("خیر",callback_data=f"st:{uid2}")]]
        await show(q,"مطمئنی؟",kb)
    elif d.startswith("st_del_ok:"):
        uid2=int(d.split(":")[1])
        db("DELETE FROM files WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)",(uid2,),write=True)
        db("DELETE FROM sessions WHERE user_id=?",(uid2,),write=True)
        db("DELETE FROM students WHERE user_id=?",(uid2,),write=True)
        await show(q,"🗑 حذف شد.",[[Btn("⬅️ دانش‌آموزان",callback_data="p:students")]])
    elif d=="p:asgn":
        t,kb=v_asgn();await show(q,t,kb)
    elif d=="as_new":
        ctx.user_data["new_asgn"]={};classes=db("SELECT * FROM classes ORDER BY id")
        kb=[[Btn(c["name"],callback_data=f"as_cls:{c['id']}")] for c in classes]
        await show(q,"کدام کلاس؟",kb)
    elif d.startswith("as_dur:"):
        na=ctx.user_data.get("new_asgn")
        if not na or "title" not in na or "description" not in na:await show(q,"مرحله گم شد. دوباره از /panel شروع کن.");return
        n=int(d.split(":")[1])
        if n==0:ctx.user_data["dt"]={"mode":"new","which":"start"};await dt_ask(q,ctx)
        else:
            now=datetime.now(TZ);na["start_time"]=now_str();na["end_time"]=(now+timedelta(days=n)).strftime("%Y-%m-%d %H:%M");await save_new(q,ctx,uid)
    elif d=="dt_cancel":
        for k in("dt","new_asgn","step"):ctx.user_data.pop(k,None)
        await show(q,"لغو شد.",[[Btn("✖️ بستن",callback_data="p:home")]])
    elif d.startswith("dt_"):
        if ctx.user_data.get("dt"):await dt_step(q,ctx,d)
    elif d.startswith("as_cls:"):
        cid=int(d.split(":")[1]);ctx.user_data["new_asgn"]["class_id"]=cid;ctx.user_data["step"]="as_title"
        await show(q,"نام تکالیف (مثلاً: تکالیف جلسه ۵):")
    elif d.startswith("as:"):
        aid=int(d.split(":")[1]);asgn=db("SELECT * FROM assignments WHERE id=?",(aid,),one=True)
        n_sent=db("SELECT COUNT(DISTINCT user_id) c FROM sessions WHERE assignment_id=? AND status='sent'",(aid,),one=True)["c"]
        n_total=db("SELECT COUNT(*) c FROM students WHERE class_id=?",(asgn["class_id"],),one=True)["c"]
        kb=[[Btn("📊 وضعیت",callback_data=f"as_status:{aid}"),Btn("✏️ عوض کن",callback_data=f"as_edit:{aid}")],[Btn("📥 گزارش PDF",callback_data=f"as_pdf:{aid}"),Btn("🗑 حذف",callback_data=f"as_del:{aid}")],[Btn("⬅️ بازگشت",callback_data="p:asgn")]]
        await show(q,f"📚 {e(asgn['title'])}\n{e(asgn['description']or '—')}\n🕒 {shamsi(asgn['start_time'])} تا {shamsi(asgn['end_time'])}\n✅ {n_sent}/{n_total} نفر",kb)
    elif d.startswith("as_status:"):
        aid=int(d.split(":")[1]);asgn=db("SELECT * FROM assignments WHERE id=?",(aid,),one=True)
        sent=db("SELECT DISTINCT st.name FROM sessions se JOIN students st ON st.user_id=se.user_id WHERE se.assignment_id=? AND se.status='sent' ORDER BY st.name",(aid,))
        not_sent=db("SELECT st.name FROM students st WHERE st.class_id=? AND st.user_id NOT IN (SELECT DISTINCT user_id FROM sessions WHERE assignment_id=? AND status='sent')",(asgn["class_id"],aid))
        text=f"✅ تحویل داده ({len(sent)}):\n"+"\n".join(f"• {e(r['name'])}"for r in sent or[])+f"\n\n❌ تحویل نداده ({len(not_sent)}):\n"+"\n".join(f"• {e(r['name'])}"for r in not_sent or[])
        await show(q,text[:2000],[[Btn("⬅️ بازگشت",callback_data=f"as:{aid}")]])
    elif d.startswith("as_edit:"):
        aid=int(d.split(":")[1])
        kb=[[Btn("عنوان",callback_data=f"as_edit_f:{aid}:title")],[Btn("توضیحات",callback_data=f"as_edit_f:{aid}:description")],[Btn("زمان شروع",callback_data=f"as_edit_f:{aid}:start_time")],[Btn("زمان پایان",callback_data=f"as_edit_f:{aid}:end_time")],[Btn("⬅️ بازگشت",callback_data=f"as:{aid}")]]
        await show(q,"کدام را عوض کنیم؟",kb)
    elif d.startswith("as_edit_f:"):
        _,aid,fld=d.split(":")
        if fld in("start_time","end_time"):
            ctx.user_data["dt"]={"mode":"edit","which":"start"if fld=="start_time" else "end","aid":int(aid)};await dt_ask(q,ctx);return
        ctx.user_data["edit_field"]=fld;ctx.user_data["edit_aid"]=int(aid);ctx.user_data["step"]="edit"
        lbl={"title":"عنوان جدید:","description":"توضیحات جدید:","start_time":"زمان شروع (2026-10-27 14:30):","end_time":"زمان پایان (2026-10-27 16:30):"}
        await show(q,lbl.get(fld,"مقدار:"))
    elif d.startswith("as_pdf:"):
        aid=int(d.split(":")[1]);asgn=db("SELECT * FROM assignments WHERE id=?",(aid,),one=True)
        rows=db("SELECT st.name,st.username,MAX(se.sent_at) sent_at FROM sessions se JOIN students st ON st.user_id=se.user_id WHERE se.assignment_id=? AND se.status='sent' GROUP BY st.user_id ORDER BY st.name",(aid,))
        try:
            buffer=generate_pdf(asgn,rows)
        except Exception as ex:
            await q.message.reply_text(f"❌ خطا در ساخت PDF: {ex}");return
        safe=re.sub(r'[\\/:*?"<>|]','',asgn['title'] or "").strip()[:20] or "report"
        await ctx.bot.send_document(chat_id,buffer,filename=f"{safe}.pdf")
    elif d.startswith("as_del:"):
        aid=int(d.split(":")[1])
        kb=[[Btn("✅ بله",callback_data=f"as_del_ok:{aid}"),Btn("خیر",callback_data=f"as:{aid}")]]
        await show(q,"حذف شود؟",kb)
    elif d.startswith("as_del_ok:"):
        aid=int(d.split(":")[1])
        db("DELETE FROM files WHERE session_id IN (SELECT id FROM sessions WHERE assignment_id=?)",(aid,),write=True)
        db("DELETE FROM sessions WHERE assignment_id=?",(aid,),write=True)
        db("DELETE FROM assignments WHERE id=?",(aid,),write=True)
        await show(q,"🗑 حذف شد.",[[Btn("⬅️ تکالیف",callback_data="p:asgn")]])
    elif d=="p:report":
        t,kb=v_report();await show(q,t,kb)
    elif d.startswith("rep:"):
        cid=int(d.split(":")[1]);asgns=db("SELECT * FROM assignments WHERE class_id=? ORDER BY id DESC",(cid,))
        text=""
        for a in asgns:
            n=db("SELECT COUNT(DISTINCT user_id) c FROM sessions WHERE assignment_id=? AND status='sent'",(a["id"],),one=True)["c"]
            total=db("SELECT COUNT(*) c FROM students WHERE class_id=?",(cid,),one=True)["c"]
            text+=f"📚 {e(a['title'])}: {n}/{total}\n"
        await show(q,text or "تکلیفی نیست.",[[Btn("⬅️ بازگشت",callback_data="p:report")]])

async def dt_ask(q,ctx,err=""):
    dt=ctx.user_data["dt"];w="شروع" if dt["which"]=="start" else "پایان"
    got=[fa(dt["y"])if"y"in dt else None,MONTHS[dt["m"]-1]if"m"in dt else None,fa(dt["d"])if"d"in dt else None,fa(f"{dt['h']:02d}")if"h"in dt else None]
    chosen=" / ".join(x for x in got if x)
    if "y" not in dt:
        jy=jnow()[0];ask="سال؟";kb=[[Btn(fa(jy),callback_data=f"dt_y:{jy}"),Btn(fa(jy+1),callback_data=f"dt_y:{jy+1}")]]
    elif "m" not in dt:
        ask="ماه؟";btns=[Btn(MONTHS[i],callback_data=f"dt_m:{i+1}") for i in range(12)];kb=[btns[i:i+3] for i in range(0,12,3)]
    elif "d" not in dt:
        n=jdays(dt["y"],dt["m"]);ask="روز؟";btns=[Btn(fa(x),callback_data=f"dt_d:{x}") for x in range(1,n+1)];kb=[btns[i:i+7] for i in range(0,n,7)]
    elif "h" not in dt:
        ask="ساعت؟";btns=[Btn(fa(f"{x:02d}"),callback_data=f"dt_h:{x}") for x in range(24)];kb=[btns[i:i+6] for i in range(0,24,6)]
    else:
        ask="دقیقه؟";btns=[Btn(fa(f"{x:02d}"),callback_data=f"dt_i:{x}") for x in range(0,60,5)];kb=[btns[i:i+4] for i in range(0,12,4)]
    kb.append([Btn("❌ لغو",callback_data="dt_cancel")])
    head=(f"{err}\n\n" if err else "")+f"🕒 زمان {w}\n"+(f"{chosen}\n" if chosen else "")+f"\n{ask}"
    await show(q,head,kb)

async def save_new(q,ctx,uid):
    na=ctx.user_data.pop("new_asgn");ctx.user_data.pop("step",None);ctx.user_data.pop("dt",None)
    aid=db("INSERT INTO assignments(class_id,title,description,start_time,end_time,created_by,created_at)VALUES(?,?,?,?,?,?,?)",(na["class_id"],na["title"],na["description"],na["start_time"],na["end_time"],uid,now_str()),write=True)
    ok,total=await notify_students(ctx.bot,aid,na)
    await show(q,f"✅ تکالیف «{e(na['title'])}» ثبت شد.\n🕒 {shamsi(na['start_time'])} تا {shamsi(na['end_time'])}\n🔔 اطلاع‌رسانی به {fa(ok)} از {fa(total)} دانش‌آموز",[[Btn("📚 مشاهده",callback_data=f"as:{aid}")],[Btn("✖️ بستن",callback_data="p:home")]])

async def notify_students(bot,aid,na):
    students=db("SELECT user_id FROM students WHERE class_id=?",(na["class_id"],))
    msg=f"{pick('🔔 تکلیف جدید ثبت شد 📢','📣 تکلیف تازه‌ای برای شما ثبت شد','✨ تکلیف جدید در دسترس است')}\n📚 {e(na['title'])}\n"
    if na.get("description"):msg+=f"📝 {e(na['description'])}\n"
    msg+=f"🕒 {shamsi(na['start_time'])} تا {shamsi(na['end_time'])}\n\n"+pick("موفق باشید 🌸","برایتان آرزوی موفقیت داریم 🌟","با آرزوی موفقیت ✨")
    kb=Markup([[Btn("📤 ارسال تکلیف",callback_data=f"a:{aid}")]])
    ok=0
    for s in students:
        try:
            await bot.send_message(s["user_id"],msg,reply_markup=kb,parse_mode=HTML);ok+=1
        except Exception as ex:
            logging.warning(f"notify failed for {s['user_id']}: {ex}")
    return ok,len(students)

async def dt_step(q,ctx,d):
    dt=ctx.user_data["dt"];k,v=d.split(":");key={"dt_y":"y","dt_m":"m","dt_d":"d","dt_h":"h","dt_i":"i"}.get(k)
    nxt=next((x for x in "ymdhi" if x not in dt),None)
    if key is None or key!=nxt:return
    dt[key]=int(v)
    if "i" not in dt:await dt_ask(q,ctx);return
    s_=j2s(dt["y"],dt["m"],dt["d"],dt["h"],dt["i"]);which=dt["which"]
    if dt["mode"]=="new":
        na=ctx.user_data["new_asgn"]
        if which=="start":
            na["start_time"]=s_;ctx.user_data["dt"]={"mode":"new","which":"end"};await dt_ask(q,ctx);return
        if s_<=na["start_time"]:
            ctx.user_data["dt"]={"mode":"new","which":"end"};await dt_ask(q,ctx,"❌ زمان پایان باید بعد از زمان شروع باشد. دوباره انتخاب کن.");return
        na["end_time"]=s_;await save_new(q,ctx,q.from_user.id)
    else:
        aid=dt["aid"];a=db("SELECT * FROM assignments WHERE id=?",(aid,),one=True)
        other=a["end_time"]if which=="start" else a["start_time"]
        if other and((which=="start" and s_>=other)or(which=="end" and s_<=other)):
            ctx.user_data["dt"]={"mode":"edit","which":which,"aid":aid};await dt_ask(q,ctx,"❌ زمان شروع باید قبل از پایان باشد. دوباره انتخاب کن.");return
        db(f"UPDATE assignments SET {'start_time' if which=='start' else 'end_time'}=? WHERE id=?",(s_,aid),write=True)
        ctx.user_data.pop("dt",None);await show(q,"✅ ذخیره شد.",[[Btn("⬅️ بازگشت",callback_data=f"as:{aid}")]])

async def show(q,text,kb=None):
    try:await q.edit_message_text(text,reply_markup=Markup(kb)if kb else None,parse_mode=HTML)
    except BadRequest:pass

async def send_session(bot,chat_id,sid):
    sess=db("SELECT se.*,a.title,st.name FROM sessions se JOIN assignments a ON a.id=se.assignment_id JOIN students st ON st.user_id=se.user_id WHERE se.id=?",(sid,),one=True)
    if not sess:return
    files=db("SELECT * FROM files WHERE session_id=?",(sid,))
    await bot.send_message(chat_id,f"📂 {e(sess['name'])} - {e(sess['title'])}\n🕒 {shamsi(sess['sent_at'])}",parse_mode=HTML)
    for f in files:
        if f["kind"]=="photo":await bot.send_photo(chat_id,f["file_id"])
        else:await bot.send_document(chat_id,f["file_id"])

# ---------------- PDF (فارسی) ----------------
FONT_NAME="Fa"
FONT_CANDIDATES=("Vazir-Regular.ttf","Vazir.ttf","Vazirmatn-Regular.ttf","Sahel.ttf","Samim.ttf")
WIN_FONTS=("C:/Windows/Fonts/tahoma.ttf","C:/Windows/Fonts/arial.ttf","C:/Windows/Fonts/segoeui.ttf")
HAS_FA_DIGITS=False

def _register_font():
    global HAS_FA_DIGITS
    base=os.path.dirname(os.path.abspath(__file__))
    paths=[os.path.join(base,n) for n in FONT_CANDIDATES]+list(WIN_FONTS)
    for p in paths:
        if not os.path.exists(p):continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME,p))
            cmap=pdfmetrics.getFont(FONT_NAME).face.charToGlyph
        except Exception:
            continue
        # حروف فارسی (فرم نمایشی): ا، ف، ی، ک، پ، گ
        need=(0xFE8D,0xFED1,0xFBFE,0xFEDB,0xFB57,0xFB93)
        if all(c in cmap for c in need):
            HAS_FA_DIGITS=0x06F1 in cmap
            logging.info(f"PDF font: {p} (ارقام فارسی: {HAS_FA_DIGITS})")
            return True
    return False
HAS_FONT=_register_font()

def fp(x):
    """متن فارسی را برای PDF آماده می‌کند (اتصال حروف + راست‌به‌چپ)"""
    s=str(x or "")
    if not HAS_FA_DIGITS:
        s=s.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789"))
    return get_display(arabic_reshaper.reshape(s))

def generate_pdf(asgn,rows):
    if not HAS_FONT:raise RuntimeError("فونت فارسی پیدا نشد؛ Vazirmatn-Regular.ttf را کنار فایل ربات بگذار.")
    buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=30,leftMargin=30,topMargin=30,bottomMargin=30)
    title_st=ParagraphStyle("T",fontName=FONT_NAME,fontSize=16,leading=24,alignment=1)
    rtl_st=ParagraphStyle("R",fontName=FONT_NAME,fontSize=11,leading=18,alignment=2)
    story=[Paragraph(html.escape(fp(f"گزارش تکالیف: {asgn['title']}")),title_st),
           Paragraph(html.escape(fp(f"بازه زمانی: {shamsi(asgn['start_time'])} تا {shamsi(asgn['end_time'])}")),rtl_st),
           Spacer(1,20)]
    header=["ردیف","نام","یوزرنیم","زمان ارسال"]
    data=[[fp(h) for h in header][::-1]]
    for i,r in enumerate(rows,1):
        un=f"@{r['username']}" if r["username"] else "—"
        data.append([fp(x) for x in (fa(i),r["name"],un,shamsi(r["sent_at"]))][::-1])
    tbl=Table(data,colWidths=[140,110,150,60],repeatRows=1)
    tbl.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),FONT_NAME),
        ('FONTSIZE',(0,0),(-1,-1),10),
        ('BACKGROUND',(0,0),(-1,0),colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BOTTOMPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),8),
        ('GRID',(0,0),(-1,-1),0.7,colors.black)]))
    story.append(tbl);doc.build(story);buffer.seek(0);return buffer

async def receive_file(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if is_teacher(uid):return
    st=db("SELECT * FROM students WHERE user_id=?",(uid,),one=True)
    if not st:await update.message.reply_text(pick("لطفاً ابتدا ثبت‌نام کنید 🌸 برای شروع /start را بزنید","برای استفاده از ربات، ابتدا /start را بزنید 🙏"));return
    sess=db("SELECT * FROM sessions WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",(uid,),one=True)
    if not sess:await update.message.reply_text(pick("لطفاً ابتدا یک تکلیف را از منو انتخاب کنید 📚","ابتدا از منو تکلیف مورد نظر را انتخاب کنید 🌸 سپس فایل را بفرستید"));return
    m=update.message
    if m.photo:fid,kind=m.photo[-1].file_id,"photo"
    else:fid,kind=m.document.file_id,"document"
    db("INSERT INTO files(session_id,file_id,kind)VALUES(?,?,?)",(sess["id"],fid,kind),write=True)
    n=db("SELECT COUNT(*) c FROM files WHERE session_id=?",(sess["id"],),one=True)["c"]
    await update.message.reply_text(pick(f"✅ {fa(n)} فایل ذخیره شد.",f"دریافت شد 📥 تعداد فایل‌های شما: {fa(n)} 🌿",f"سپاس ✨ تا اینجا {fa(n)} فایل دریافت شده است. در صورت نیاز ادامه دهید 📎"))

async def sticker_id(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if is_teacher(update.effective_user.id):
        await update.message.reply_text(f"file_id استیکر:\n<code>{update.message.sticker.file_id}</code>",parse_mode=HTML)

async def done(update:Update,ctx:ContextTypes.DEFAULT_TYPE):await update.message.reply_text(pick("برای ارسال، دکمه «📤 ارسال» را از همان منو بزنید 🌸","کافی است دکمه «✅ تموم» یا «📤 ارسال» را بزنید 👆"))

async def panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_teacher(update.effective_user.id):return
    await update.message.reply_text("🛠 پنل معلم 🌿\nاز دکمه‌های پایین استفاده کنید 👇",reply_markup=kb_teacher())

async def cancel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id;ctx.user_data.clear()
    if is_teacher(uid):kb=kb_teacher()
    elif db("SELECT 1 FROM students WHERE user_id=?",(uid,),one=True):kb=kb_student()
    else:kb=ReplyKeyboardRemove()
    await update.message.reply_text(pick("بسیار خوب، لغو شد 🌿","عملیات لغو شد 🙏"),reply_markup=kb)

def main():
    if not TOKEN:raise SystemExit("BOT_TOKEN تنظیم نشده؛ فایل .env را بساز (نمونه: .env.example).")
    init_db()
    if not TEACHERS:print("⚠️ TEACHER_IDS در فایل .env تنظیم نشده؛ پنل معلم کار نخواهد کرد.")
    if not HAS_FONT:print("⚠️ فونت فارسی پیدا نشد؛ ساخت PDF کار نخواهد کرد.")
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("panel",panel))
    app.add_handler(CommandHandler("cancel",cancel))
    app.add_handler(CommandHandler("done",done))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.Sticker.ALL,sticker_id))
    app.add_handler(MessageHandler(filters.PHOTO|filters.Document.ALL,receive_file))
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,on_text))
    app.run_polling()

if __name__=="__main__":main()
