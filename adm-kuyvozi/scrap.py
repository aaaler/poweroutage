import requests,logging,os,wget,urllib,datetime,time
import pdf2image
from bs4 import BeautifulSoup
from hashlib import md5
from peewee import *
from PIL import Image,ImageFont,ImageDraw
import pytesseract

cachedir = "./cache/"
def pdf_to_img(pdf_file):
    return pdf2image.convert_from_path(pdf_file)

def scrape (cachedir):
    url = "https://adm-kyivozy.ru/news/c:elektroenergiya"
    cached = os.listdir(cachedir)
    r1 = requests.get(url)
    newsfeedpage = r1.content
    newsfeedsoup = BeautifulSoup(newsfeedpage, 'html5lib')
    articles = []
    for article in newsfeedsoup.find_all('a', class_='uk-card'):
        href = article['href']
        cachedname = cachedir + md5(href.encode('utf-8')).hexdigest()
        if md5(href.encode('utf-8')).hexdigest() not in cached:
            rec, rec_created = Record.get_or_create (URL=href)
            rec.title = article.find_all('h3')[0].string.strip()
            if rec_created: rec.save()
            logging.info ("Fetching article {}".format(href))
            r1 = requests.get(href)
            articlepage = r1.content
            articlesoup = BeautifulSoup(articlepage, 'html5lib')
            for subarticle in articlesoup.find_all('a', href=True, attrs={'class':'uk-button-small'}):
                docurl = subarticle['href']
                logging.info ("Fetching pic {} to {}".format(docurl,cachedname))
                try:
                    urllib.request.urlretrieve(urllib.parse.quote(docurl, safe='/:'), cachedname)
                except urllib.error.HTTPError as err:
                    with open(cachedname, 'w') as f:
                        logging.warning ("HTTP error {} to {}".format(err,cachedname))
                        f.write(str(err))
                        rec.text=str(err)
                images = pdf_to_img(cachedname)
                image = images[0]
                rec.text = pytesseract.image_to_string(image, lang='rus')
                watermark_image = image.copy()
                draw = ImageDraw.Draw(watermark_image)
                font = ImageFont.truetype("NotoSansMono-Medium.ttf", 20)
                draw.text((0, 0), "https://t.me/svet_v_vaskelovo", (0, 0, 0), font=font)
                watermark_image.save(cachedname,"JPEG")

            rec.save()

def notify_tg ():
    import telegram
    bot = telegram.Bot(token=os.environ.get('TG_TOKEN'))
    query = Record.select().where((Record.text ** '%620-210%' | Record.text ** '%620-110%' | Record.text ** '%Троицкое%' | Record.text ** '%ЛОМО%') & (Record.notification_sent == False)).order_by(Record.created.desc())
    for r in query:
        logging.info("Sending alert about {} ({})".format(r.title, r.URL))
        f = open('./cache/' + md5(r.URL.encode('utf-8')).hexdigest(), 'rb')
        bot.send_photo(caption=r.title, photo=f, chat_id=os.environ.get('TG_CHATID'))
        f.close()
        r.notification_sent = True
        r.save()

db = SqliteDatabase(cachedir + 'feed.db')
class Record(Model):
    URL = CharField(unique=True)
    title = CharField(null = True)
    created = DateTimeField(default=datetime.datetime.now,null = True)
    begin = DateField(null = True)
    text = TextField(null = True)
    notification_needed = BooleanField(default=False)
    notification_sent = BooleanField(default=False)
    class Meta:
        database = db
db.connect()
db.create_tables([Record], safe=True)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


while True:
    scrape ( cachedir )
    notify_tg ()
    logging.info("Sleeping for another {} seconds".format(os.environ.get('SLEEP')))
    time.sleep(int(os.environ.get('SLEEP')))

