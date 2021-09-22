import requests,logging,os,wget,urllib,datetime,time
from bs4 import BeautifulSoup
from hashlib import md5
from peewee import *
try:
    from PIL import Image
except ImportError:
    import Image
import pytesseract

cachedir = "./cache/"

def scrape (cachedir):
    url = "http://adm-kyivozy.ru/index.php?page=news"
    cached = os.listdir(cachedir)
    r1 = requests.get(url)
    newsfeedpage = r1.content
    newsfeedsoup = BeautifulSoup(newsfeedpage, 'html5lib')
    articles = []
    for article in newsfeedsoup.find_all('div', class_='NewsSummary'):
        href = article.find_all("a")[0]['href']
        cachedname = cachedir + md5(href.encode('utf-8')).hexdigest()
        if md5(href.encode('utf-8')).hexdigest() not in cached:
            rec, rec_created = Record.get_or_create (URL=href)
            rec.title = article.find_all("a")[0]['title']
            if rec_created: rec.save()
            r1 = requests.get(href)
            articlepage = r1.content
            articlesoup = BeautifulSoup(articlepage, 'html5lib')
            if articlesoup.select('#NewsPostDetailContent')[0].find("img"):
                docurl = articlesoup.select('#NewsPostDetailContent')[0].find("img")['src']
                logging.info ("Fetching pic {} to {}".format(docurl,cachedname))
                try:
                    wget.download('http://adm-kyivozy.ru/' + docurl, cachedname,bar=None)
                    rec.text = pytesseract.image_to_string(Image.open(cachedname), lang='rus')
                except urllib.error.HTTPError as err:
                    with open(cachedname, 'w') as f:
                        logging.warning ("Cached HTTP error {} to {}".format(err,cachedname))
                        f.write(str(err))
                        rec.text=str(err)
            else:
                with open(cachedname, 'w') as f:
                    logging.info ("Fetching text from {} to {}".format(href,cachedname))
                    text_content = str(articlesoup.select('#NewsPostDetailContent'))
                    f.write(text_content)
                    rec.text=text_content
            rec.save()

def notify_tg ():
    import telegram
    bot = telegram.Bot(token=os.environ.get('TG_TOKEN'))
    query = Record.select().where((Record.text ** '%620-210%' | Record.text ** '%Троицкое%' | Record.text ** '%ЛОМО%') & (Record.notification_sent == False))
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

