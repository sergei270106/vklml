import logging
import logging.handlers
import sys
import os
import json
import sqlite3
import signal
import threading
import time
import difflib
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import requests.exceptions

cwd = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    level=logging.WARNING
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(
    os.path.join(cwd, 'log.txt'),
    maxBytes=102400
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.info("Запуск...")

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Непойманное исключение.", exc_info=(exc_type, exc_value, exc_traceback))
sys.excepthook = handle_exception

defaultConfig = {
    "ACCESS_TOKEN": "",
    "createIndex": False,
    "maxCacheAge": 86400,
    "customActions": False,
    "disableMessagesLogging": False,
    "placeTokenInGetVideo": True,
    "tokenToPlaceInGetVideo": "",
    'enableFlaskWebServer': False,
    'useAuth': False,
    'users': {
        'admin':'password'
    },
    'port': 8080,
    'https': False,
    'httpsPort': 8443,
    'cert': [
        os.path.join(cwd, "cert.pem"),
        os.path.join(cwd, "key.pem")
    ]
}

def grab_token_from_args():
    if len(sys.argv) > 1:
        defaultConfig['ACCESS_TOKEN'] = sys.argv[1]
    if defaultConfig['ACCESS_TOKEN'] == "":
        raise Exception("Не задан ACCESS_TOKEN")

try:
    with open(os.path.join(cwd, "config.json"), 'r') as conf:
        config = json.load(conf)
    for i in config:
        if i in defaultConfig:
            defaultConfig[i] = config[i]
    grab_token_from_args()
    if len(set(config) - set(defaultConfig)) != 0:
        with open(os.path.join(cwd, "config.json"), 'w') as conf:
            json.dump(defaultConfig, conf, indent=4)
    config = defaultConfig
    del defaultConfig
except (FileNotFoundError, json.decoder.JSONDecodeError):
    with open(os.path.join(cwd, "config.json"), 'w') as conf:
        grab_token_from_args()
        json.dump(defaultConfig, conf, indent=4)
        config = defaultConfig
        del defaultConfig

stop = False

def run_flask_server():
    port = config['httpsPort'] if config['https'] else config['port']
    import socket
    ip = socket.gethostbyname(socket.gethostname())
    del socket
    while True:
        try:
            if config['https']:
                logger.info("Trying to run on https://%s:%s/", ip, port)
                app.run(
                    host='0.0.0.0',
                    port=port,
                    ssl_context=(
                        config['cert'][0],
                        config['cert'][1]
                    )
                )
            else:
                logger.info("Trying to run on http://%s:%s/", ip, port)
                app.run(host='0.0.0.0', port=port)
        except OSError:
            port += 1

if config['enableFlaskWebServer']:
    from flaskWebServer import app
    threading.Thread(target=run_flask_server).start()

if config['createIndex']:
    from updateIndex import indexUpdater
    indexUpdater()

def tryAgainIfFailed(func, *args, delay=5, maxRetries=5, **kwargs):
    c = maxRetries
    while True:
        try:
            return func(*args, **kwargs)
        except vk_api.exceptions.ApiError:
            if str(sys.exc_info()[1]).find("User authorization failed") != -1:
                logger.warning("Токен недействителен.")
                interrupt_handler(0, None)
            raise Warning
        except requests.exceptions.RequestException:
            time.sleep(delay)
            continue
        except BaseException:
            if maxRetries == 0:
                logger.exception("После %s попыток %s(%s%s) завершился с ошибкой.", c, func.__name__, args, kwargs)
                raise Warning
            logger.warning("Перезапуск %s(%s%s) через %s секунд...", func.__name__, args, kwargs, delay)
            time.sleep(delay)
            if maxRetries > 0:
                maxRetries -= 1
            continue

vk_session = vk_api.VkApi(token=config['ACCESS_TOKEN'])
longpoll = VkLongPoll(vk_session, wait=10, mode=2)
vk = vk_session.get_api()
account_id = tryAgainIfFailed(
    vk.users.get,
    delay=1
)[0]['id']

if not config['disableMessagesLogging']:
    if not os.path.exists(
        os.path.join(
            cwd,
            "mesAct"
        )
    ):
        os.makedirs(
            os.path.join(
                cwd,
                "mesAct"
            )
        )
    f = open(
        os.path.join(
            cwd,
            "mesAct",
            "vkGetVideoLink.html"
        ),
        'w',
        encoding='utf-8'
    )
    f.write("""<!DOCTYPE html>
    <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body>
            <input id="videos"></input>
            <input type="submit" id="submit" value="Отправить">
            <div><p>Если видео не проигрывается, прямую ссылку можно получить через api:</p></div>
            <div style="position:relative;padding-top:56.25%;"></div>
            <script>
                let ACCESS_TOKEN = '{}';
                document.getElementById('submit').onclick = function() {{
                    var link = document.createElement('a');
                    link.href = "https://vk.com/dev/video.get?params[videos]=0_0," + videos.value + "&params[count]=1&params[offset]=1";
                    link.innerText = videos.value;
                    document.getElementById('submit').disabled = true;
                    document.getElementsByTagName("div")[0].appendChild(link);
                    var script = document.createElement('SCRIPT');
                    script.src = "https://api.vk.com/method/video.get?v=5.101&access_token=" + ACCESS_TOKEN + "&videos=" + videos.value + "&callback=callbackFunc";
                    document.getElementsByTagName("head")[0].appendChild(script);
                }}
                function callbackFunc(result) {{
                    var frame = document.createElement('iframe');
                    frame.src = result.response.items[0]["player"];
                    frame.style = "position:absolute;top:0;left:0;width:100%;height:100%;";
                    document.getElementsByTagName("div")[1].appendChild(frame);
                }}
                let videos = document.getElementById('videos');
                videos.value = document.location.search.slice(1);
                if (videos.value != "") document.getElementById('submit').click()
            </script>
        </body>
    </html>""".format(config['tokenToPlaceInGetVideo'] if config['tokenToPlaceInGetVideo'] != "" else config['ACCESS_TOKEN'] if config['placeTokenInGetVideo'] else ""))
    f.close()
    if not os.path.exists(
        os.path.join(
            cwd,
            "messages.db"
        )
    ):
        conn = sqlite3.connect(
            os.path.join(
                cwd,
                "messages.db"
            ),
            check_same_thread=False,
            timeout=15.0
        )
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE "messages" (
        "peer_id"	INTEGER NOT NULL,
        "user_id"	INTEGER NOT NULL,
        "message_id"	INTEGER NOT NULL UNIQUE,
        "message"	TEXT,
        "attachments"	TEXT,
        "timestamp"	INTEGER NOT NULL,
        "fwd_messages"  TEXT
)""")
        cursor.execute("""CREATE TABLE "chats_cache" (
        "chat_id"	INTEGER NOT NULL UNIQUE,
        "chat_name"	TEXT NOT NULL
)""")
        cursor.execute("""CREATE TABLE "users_cache" (
        "user_id"	INTEGER NOT NULL UNIQUE,
        "user_name"	TEXT NOT NULL
)""")
        account_name = tryAgainIfFailed(
            vk.users.get,
            delay=1,
            user_id=account_id
        )[0]
        account_name = f"{account_name['first_name']} {account_name['last_name']}"
        cursor.execute(
            """INSERT INTO users_cache (user_id,user_name) VALUES (?,?)""",
            (account_id, account_name,)
        )
        conn.commit()
    else:
        conn = sqlite3.connect(
            os.path.join(cwd, "messages.db"),
            check_same_thread=False,
            timeout=15.0
        )
        cursor = conn.cursor()
    if not os.path.exists(
        os.path.join(
            cwd,
            "mesAct",
            "bootstrap.css"
        )
    ):
        f = open(
            os.path.join(
            cwd,
            "mesAct",
            "bootstrap.css"
            ),
            'w',
            encoding='utf-8'
        )
        f.write(':root{--blue:#007bff;--indigo:#6610f2;--purple:#6f42c1;--pink:#e83e8c;--red:#dc3545;--orange:#fd7e14;--yellow:#ffc107;--green:#28a745;--teal:#20c997;--cyan:#17a2b8;--white:#fff;--gray:#6c757d;--gray-dark:#343a40;--primary:#007bff;--secondary:#6c757d;--success:#28a745;--info:#17a2b8;--warning:#ffc107;--danger:#dc3545;--light:#f8f9fa;--dark:#343a40;--breakpoint-xs:0;--breakpoint-sm:576px;--breakpoint-md:768px;--breakpoint-lg:992px;--breakpoint-xl:1200px;--font-family-sans-serif:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif,"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol","Noto Color Emoji";--font-family-monospace:SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}*,::after,::before{box-sizing:border-box}html{font-family:sans-serif;line-height:1.15;-webkit-text-size-adjust:100%;-webkit-tap-highlight-color:transparent}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif,"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol","Noto Color Emoji";font-size:1rem;font-weight:400;line-height:1.5;color:#212529;text-align:left;background-color:#fff}dl,ol,ul{margin-top:0;margin-bottom:1rem}b,strong{font-weight:bolder}a{color:#007bff;text-decoration:none;background-color:transparent}img{vertical-align:middle;border-style:none}table{border-collapse:collapse}.table{width:100%;margin-bottom:1rem;color:#212529}.table td,.table th{padding:.75rem;vertical-align:top;border-top:1px solid #dee2e6}.table-sm td,.table-sm th{padding:.3rem}.table-bordered{border:1px solid #dee2e6}.table-bordered td,.table-bordered th{border:1px solid #dee2e6}.list-group{display:-ms-flexbox;display:flex;-ms-flex-direction:column;flex-direction:column;padding-left:0;margin-bottom:0;border-radius:.25rem}.list-group-item{position:relative;display:block;padding:.75rem 1.25rem;background-color:#fff;border:1px solid rgba(0,0,0,.125)}.list-group-item:first-child{border-top-left-radius:inherit;border-top-right-radius:inherit}.list-group-item:last-child{border-bottom-right-radius:inherit;border-bottom-left-radius:inherit}.list-group-item+.list-group-item{border-top-width:0}.stretched-link::after{position:absolute;top:0;right:0;bottom:0;left:0;z-index:1;pointer-events:auto;content:"";background-color:rgba(0,0,0,0)}.mes{word-break:break-all}img,a,audio{display:block}img{max-width:300px}')
        f.close()

if config['customActions']:
    from customActions import customActions
    cust = customActions(vk, conn, cursor)

def bgWatcher():
    global stop
    while True:
        maxCacheAge = config['maxCacheAge']
        while stop:
            time.sleep(2)
        stop = True
        logger.info("Обслуживание БД...")
        try:
            showMessagesWithDeletedAttachments()
        except BaseException:
            logger.exception("Ошибка при поиске удаленных фото")
        try:
            if maxCacheAge != -1:
                cursor.execute(
                    """DELETE FROM messages WHERE timestamp < ?""",
                    (time.time() - maxCacheAge,)
                )
                conn.commit()
                cursor.execute("VACUUM")
            else:
                maxCacheAge = 86400
        except BaseException:
            logger.exception("Ошибка при очистке базы данных")
        stop = False
        logger.info("Обслуживание БД завершено.")
        time.sleep(maxCacheAge)

def interrupt_handler(signum, frame):
    conn.commit()
    cursor.close()
    try:
        tableWatcher.cancel()
    except AttributeError:
        pass
    logger.info("Завершение...")
    os._exit(0)

signal.signal(signal.SIGINT, interrupt_handler)
signal.signal(signal.SIGTERM, interrupt_handler)

def eventWorker_predefinedDisabled():
    global events
    global stop
    while True:
        flag.wait()
        event = events.pop(0)
        while stop:
            time.sleep(2)
        stop = True
        try:
            cust.act(event)
        except BaseException:
            logger.exception("Ошибка в customActions. \n %s", vars(event))
        stop = False
        if len(events) == 0:
            flag.clear()

def eventWorker_customDisabled():
    global events
    global stop
    while True:
        flag.wait()
        event = events.pop(0)
        while stop:
            time.sleep(2)
        stop = True
        predefinedActions(event)
        stop = False
        if len(events) == 0:
            flag.clear()
            conn.commit()

def eventWorker():
    global events
    global stop
    while True:
        flag.wait()
        event = events.pop(0)
        while stop:
            time.sleep(2)
        stop = True
        try:
            cust.act(event)
        except BaseException:
            logger.exception("Ошибка в customActions. \n %s", vars(event))
        predefinedActions(event)
        stop = False
        if len(events) == 0:
            flag.clear()
            conn.commit()

def predefinedActions(event):
    try:
        if event.type == VkEventType.MESSAGE_NEW:
            cursor.execute(
                """INSERT INTO messages(peer_id,user_id,message_id,message,attachments,timestamp,fwd_messages) VALUES (?,?,?,?,?,?,?)""",
                (event.peer_id, event.user_id, event.message_id, event.message, event.message_data[1], event.timestamp, event.message_data[2],)
            )
        elif event.type == VkEventType.MESSAGE_EDIT:
            if event.message_data[0]:
                activityReport(event.message_id, event.peer_id, event.user_id, event.timestamp, True, event.message_data[1], event.message_data[2], event.text)
            cursor.execute(
                """INSERT or REPLACE INTO messages(peer_id,user_id,message_id,message,attachments,timestamp,fwd_messages) VALUES (?,?,?,?,?,?,?)""",
                (event.peer_id, event.user_id, event.message_id, event.message, event.message_data[1], event.timestamp, event.message_data[2],)
            )
        elif event.type == VkEventType.MESSAGE_FLAGS_SET:
            try:
                activityReport(event.message_id)
                cursor.execute(
                    """DELETE FROM messages WHERE message_id = ?""",
                    (event.message_id,)
                )
            except TypeError:
                logger.info("Удаление невозможно, сообщение отсутствует в БД.")
    except sqlite3.IntegrityError:
        logger.warning("Запущено несколько копий программы, завершение...")
        interrupt_handler(0, None)
    except Warning:
        pass
    except BaseException:
        logger.exception("Ошибка при сохранении сообщения. \n %s", vars(event))

def main():
    logger.info("Запущен основной цикл.")
    global events
    for event in longpoll.listen():
        try:
            if event.raw[0] == 4 or event.raw[0] == 5:
                if event.attachments != {}:
                    event.message_data = tuple(getAttachments(event.message_id))
                else:
                    event.message_data = (True, None, None)
                if event.from_user:
                    if event.raw[2] & 2:
                        event.user_id = account_id
                elif event.from_group:
                    if event.from_me:
                        event.user_id = account_id
                    else:
                        event.user_id = event.peer_id
                if event.message == "":
                    event.message = None
                events.append(event)
                flag.set()
            elif event.raw[0] == 2 and (event.raw[2] & 131072 or event.raw[2] & 128):
                events.append(event)
                flag.set()
        except Warning:
            pass
        except BaseException:
            logger.exception("Ошибка при добавлении события в очередь. \n %s", vars(event))

def showMessagesWithDeletedAttachments():
    cursor.execute("""SELECT * FROM messages WHERE attachments IS NOT NULL""")
    fetch_attachments = [[str(i[2]), json.loads(i[4])] for i in cursor.fetchall()]
    cursor.execute("""SELECT * FROM messages WHERE fwd_messages IS NOT NULL""")
    fetch_fwd = [[str(i[2]), json.loads(i[6])] for i in cursor.fetchall()]
    c = 0
    for i in range(len(fetch_attachments)):
        for j in fetch_attachments[i - c][1]:
            if j['type'] == 'photo' or j['type'] == 'video' or j['type'] == 'doc':
                break
        else:
            del fetch_attachments[i - c]
            c += 1
    messages_attachments = []
    messages_fwd = []
    for i in [[j[0] for j in fetch_attachments[i:i + 100]] for i in range(0, len(fetch_attachments), 100)]:
        messages_attachments.extend(tryAgainIfFailed(
            vk.messages.getById,
            delay=1,
            message_ids=','.join(i))['items']
        )
    for i in [[j[0] for j in fetch_fwd[i:i + 100]] for i in range(0, len(fetch_fwd), 100)]:
        messages_fwd.extend(tryAgainIfFailed(
            vk.messages.getById,
            delay=1,
            message_ids=','.join(i))['items']
        )
    c = 0
    for i in range(len(fetch_attachments)):
        if compareAttachments(messages_attachments[i - c]['attachments'], fetch_attachments[i - c][1]):
            del fetch_attachments[i - c]
            del messages_attachments[i - c]
            c += 1
    for i in range(len(fetch_attachments)):
        activityReport(fetch_attachments[i][0])
        if messages_attachments[i]['attachments'] == []:
            cursor.execute(
                """UPDATE messages SET attachments = ? WHERE message_id = ?""",
                (None, fetch_attachments[i][0],)
            )
        else:
            cursor.execute(
                """UPDATE messages SET attachments = ? WHERE message_id = ?""",
                (
                    json.dumps(messages_attachments[i]['attachments']),
                    fetch_attachments[i][0],
                )
            )
    c = 0
    for i in range(len(fetch_fwd)):
        if compareFwd(
            messages_fwd[i - c],
            {
                'fwd_messages': fetch_fwd[i - c][1]
            }
        ):
            del fetch_fwd[i - c]
            del messages_fwd[i - c]
            c += 1
    for i in range(len(fetch_fwd)):
        activityReport(fetch_fwd[i][0])
        if messages_fwd[i]['fwd_messages'] == []:
            cursor.execute(
                """UPDATE messages SET fwd_messages = ? WHERE message_id = ?""",
                (None, fetch_fwd[i][0],)
            )
        else:
            cursor.execute(
                """UPDATE messages SET fwd_messages = ? WHERE message_id = ?""",
                (
                    json.dumps(messages_fwd[i]['fwd_messages']),
                    fetch_fwd[i][0],
                )
            )
    conn.commit()

def compareFwd(new, old):
    if 'reply_message' in new:
        new['fwd_messages'] = [new['reply_message']]
    if 'reply_message' in old:
        old['fwd_messages'] = [old['reply_message']]
    for i in range(len(old['fwd_messages'])):
        if 'fwd_messages' in old['fwd_messages'][i] and 'fwd_messages' in new['fwd_messages'][i]:
            if not compareFwd(
                new['fwd_messages'][i],
                old['fwd_messages'][i]
            ):
                return False
        if not compareAttachments(
            new['fwd_messages'][i]['attachments'],
            old['fwd_messages'][i]['attachments']
        ):
            return False
    return True

def compareAttachments(new, old):
    if len(new) < len(old):
        return False
    return True

def attachmentsParse(urls):
    if urls is None:
        return ""
    html = """<div>
                        """
    for i in urls:
        urlSplit = i.split(',')
        if i.find('sticker') != -1:
            html += """    <img src="{}" />
                        """.format(i)
        elif i.find('jpg') != -1 and i.find(',') == -1:
            html += """    <img src="{}" />
                        """.format(i)
        elif i.find('mp3') != -1:
            html += """    <audio src="{}" controls></audio>
                        """.format(i)
        elif i.find('https://vk.com/audio') != -1:
            html += """    <a href="{}" target="_blank">
                                {}
                            </a>
                        """.format(i, i[23:-11].replace('%20', ' '))
        elif i.find('@') != -1:
            i = i.split('@')
            html += """    <a href="{}" target="_blank">
                                {}
                            </a>
                        """.format(i[1], i[0])
        elif len(urlSplit) == 2:
            html += """    <a href="{}" target="_blank">
                                Видео
                                <img src="{}"/>
                            </a>
                        """.format("./vkGetVideoLink.html?" + urlSplit[1], urlSplit[0])
        else:
            html += """    <a href="{0}" target="_blank">
                                {0}
                            </a>
                        """.format(i)
    html += """</div>"""
    return html

def getAttachments(message_id):
    mes = tryAgainIfFailed(
        vk.messages.getById,
        delay=1,
        message_ids=message_id
    )['items'][0]
    hasUpdateTime = 'update_time' in mes
    fwd_messages = None
    if 'reply_message' in mes:
        fwd_messages = json.dumps([mes['reply_message']], ensure_ascii=False,)
    elif mes['fwd_messages'] != []:
        fwd_messages = json.dumps(mes['fwd_messages'], ensure_ascii=False,)
    attachments = mes['attachments']
    del mes
    if attachments == []:
        attachments = None
    else:
        attachments = json.dumps(attachments, ensure_ascii=False,)
    return hasUpdateTime, attachments, fwd_messages

def parseUrls(attachments):
    urls = []
    for i in attachments:
        if i['type'] == 'photo':
            availableSizes = []
            for j in i['photo']['sizes']:
                availableSizes.append(j['type'])
            for j in sizes:
                try:
                    realSizesIndex = availableSizes.index(j)
                except ValueError:
                    continue
                break
            urls.append(i['photo']['sizes'][realSizesIndex]['url'])
        elif i['type'] == 'audio_message':
            urls.append(i['audio_message']['link_mp3'])
        elif i['type'] == 'sticker':
            urls.append(i['sticker']['images'][0]['url'])
        elif i['type'] == 'gift':
            urls.append(i['gift']['thumb_48'])
        elif i['type'] == 'link':
            urls.append(f"Ссылка: {i['link']['title']}@{i['link']['url']}")
        elif i['type'] == 'video':
            urls.append(f"{i['video']['photo_320']},{i['video']['owner_id']}_{i['video']['id']}_{i['video']['access_key']}")
        elif i['type'] == 'wall':
            urls.append(f"Пост: {i['wall']['text'][:25]}@https://vk.com/wall{i['wall']['from_id']}_{i['wall']['id']}")
        elif i['type'] == 'wall_reply':
            urls.append(f"Комментарий: {i['wall_reply']['text'][:25]}@https://vk.com/wall{i['wall_reply']['owner_id']}_{i['wall_reply']['post_id']}?reply={i['wall_reply']['id']}")
        elif i['type'] == 'audio':
            urls.append(f"https://vk.com/audio?q={i['audio']['artist'].replace(' ', '%20')}%20-%20{i['audio']['title'].replace(' ', '%20')}&tab=global")
        elif i['type'] == 'market':
            urls.append(f"https://vk.com/market?w=product{i['market']['owner_id']}_{i['market']['id']}")
        elif i['type'] == 'poll':
            urls.append(f"Голосование: {i['poll']['question'][:25]}@https://vk.com/poll{i['poll']['owner_id']}_{i['poll']['id']}")
        elif i['type'] == 'doc':
            urls.append(f"Документ: {i['doc']['title']}@{i['doc']['url']}")
        else:
            try:
                urls.append(i[i['type']]['url'])
            except KeyError:
                pass
    if urls == []:
        return None
    return urls

def getPeerName(id):
    if id > 2000000000:
        cursor.execute("""SELECT * FROM chats_cache WHERE chat_id = ?""", (id,))
        fetch = cursor.fetchone()
        if fetch is None:
            try:
                name = tryAgainIfFailed(
                    vk.messages.getChat,
                    delay=1,
                    chat_id=id-2000000000
                )['title']
                cursor.execute("""INSERT INTO chats_cache (chat_id,chat_name) VALUES (?,?)""", (id, name,))
                conn.commit()
            except Warning:
                name = "Секретный чат, используйте токен другого приложения"
        else:
            name = fetch[1]
    elif id < 0:
        cursor.execute("""SELECT * FROM users_cache WHERE user_id = ?""", (id,))
        fetch = cursor.fetchone()
        if fetch is None:
            name = tryAgainIfFailed(
                vk.groups.getById,
                delay=1,
                group_id=-id
            )[0]['name']
            cursor.execute("""INSERT INTO users_cache (user_id,user_name) VALUES (?,?)""", (id, name,))
            conn.commit()
        else:
            name = fetch[1]
    else:
        cursor.execute("""SELECT * FROM users_cache WHERE user_id = ?""", (id,))
        fetch = cursor.fetchone()
        if fetch is None:
            name = tryAgainIfFailed(
                vk.users.get,
                delay=1,
                user_id=id
            )[0]
            name = f"{name['first_name']} {name['last_name']}"
            cursor.execute("""INSERT INTO users_cache (user_id,user_name) VALUES (?,?)""", (id, name,))
            conn.commit()
        else:
            name = fetch[1]
    return name

def fwdParse(fwd):
    html = """<table class="table table-sm table-bordered">
                        """
    for i in fwd:
        user_name = getPeerName(i['from_id'])
        if i['from_id'] < 0:
            html += """    <tr>
                                <td>
                                    <a href='https://vk.com/public{}' target="_blank">
                                        {}
                                    </a>
                                </td>
                            </tr>
                        """.format(-i['from_id'], user_name)
        else:
            html += """   <tr>
                                <td>
                                    <a href='https://vk.com/id{}' target="_blank">
                                        {}
                                    </a>
                                </td>
                            </tr>
                        """.format(i['from_id'], user_name)
        if i['text'] != "":
            html += """   <tr>
                                <td>
                                    <div class='mes'>
                                        {}
                                    </div>
                        """.format(xssFilter(i['text']))
        else:
            html += """    <tr>
                                <td>
                        """
        if i['attachments'] != []:
            html += attachmentsParse(parseUrls(i['attachments']))
        if 'fwd_messages' in i:
            html += fwdParse(i['fwd_messages'])
        elif 'reply_message' in i:
            html += fwdParse([i['reply_message']])
        html += """        </td>
                            </tr>
                        """
        html += """
                            <tr>
                                <td>
                                    {}
                                </td>
                            </tr>
                        """.format(time.strftime('%H:%M:%S %d.%m.%y', time.localtime(i['date'])))
    html += "</table>"
    return html

def xssFilter(s):
    return s\
        .replace('<', '&lt;')\
        .replace('>', '&gt;')\
        .replace('\n', '<br />')

def compareStrings(a, b):
    aCounter = 0
    bCounter = 0
    for i in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if i[0] == 'insert':
            b = f"{b[: i[3]+bCounter]}<ins>{b[i[3]+bCounter : i[4]+bCounter]}</ins>{b[i[4]+bCounter:]}"
            bCounter += 11
        elif i[0] == 'delete':
            a = f"{a[: i[1]+aCounter]}<ins>{a[i[1]+aCounter : i[2]+aCounter]}</ins>{a[i[2]+aCounter:]}"
            aCounter += 11
        elif i[0] == 'replace':
            a = f"{a[: i[1]+aCounter]}<ins>{a[i[1]+aCounter : i[2]+aCounter]}</ins>{a[i[2]+aCounter:]}"
            b = f"{b[: i[3]+bCounter]}<ins>{b[i[3]+bCounter : i[4]+bCounter]}</ins>{b[i[4]+bCounter:]}"
            aCounter += 11
            bCounter += 11
    return a, b

def activityReport(message_id, peer_id=None, user_id=None, timestamp=None, isEdited=False, attachments=None, fwd=None, message=None):
    try:
        peer_name = user_name = oldMessage = oldAttachments = date = oldFwd = None
        cursor.execute("""SELECT * FROM messages WHERE message_id = ?""", (message_id,))
        fetch = cursor.fetchone()
        if attachments is not None:
            attachments = parseUrls(json.loads(attachments))
        if fwd is not None:
            fwd = json.loads(fwd)
        if fetch is None:
            if isEdited:
                logger.info("Изменение сообщения, отсутствующего в БД, message_id = %i.", message_id)
                fetch = [0]*7
                peer_name = getPeerName(peer_id)
                user_name = getPeerName(user_id)
                oldMessage = f"⚠️ {message}"
                oldAttachments = attachments
                oldFwd = fwd
                date = f"<b>Доб:</b>&nbsp;{time.strftime('%H:%M:%S&nbsp;%d.%m', time.localtime(timestamp))}<br /><b>Изм:</b>&nbsp;{time.strftime('%H:%M:%S&nbsp;%d.%m', time.localtime())}"
            else:
                raise TypeError
        else:
            if fetch[3] is not None:
                oldMessage = str(fetch[3])
            if fetch[4] is not None:
                oldAttachments = parseUrls(json.loads(fetch[4]))
            if fetch[6] is not None:
                oldFwd = json.loads(fetch[6])
            peer_name = getPeerName(fetch[0])
            user_name = getPeerName(fetch[1])
            date = f"<b>Доб:</b>&nbsp;{time.strftime('%H:%M:%S&nbsp;%d.%m', time.localtime(fetch[5]))}<br /><b>Изм:</b>&nbsp;{time.strftime('%H:%M:%S&nbsp;%d.%m', time.localtime())}"
            peer_id = fetch[0]
            user_id = fetch[1]
        del fetch
        row = """            <tr><!-- {} -->
                <td>{}
                </td>
                <td>{}
                </td>
                {}
                <td>
                    {}
                </td>
            </tr>
"""
        messageBlock = """
                    <div class='mes'>
                        {}
                    </div>"""
        attachmentsBlock = """
                    <div>
                        <b>Вложения</b><br />
                        {}
                    </div>"""
        fwdBlock = """
                    <div>
                        <b>Пересланное</b><br />
                        {}
                    </div>"""
        if peer_id > 2000000000:
            peer_id = """
                    <a href='https://vk.com/im?sel=c{}' target='_blank'>
                        {}
                    </a>""".format(str(peer_id-2000000000), peer_name)
        elif peer_id < 0:
            peer_id = """
                    <a href='https://vk.com/public{}' target='_blank'>
                        {}
                    </a>""".format(str(-peer_id), peer_name)
        else:
            peer_id = """
                    <a href='https://vk.com/id{}' target='_blank'>
                        {}
                    </a>""".format(str(peer_id), peer_name)
        if user_id < 0:
            user_id = """
                    <a href='https://vk.com/public{}' target='_blank'>
                        {}
                    </a>""".format(str(-user_id), user_name)
        else:
            user_id = """
                    <a href='https://vk.com/id{}' target='_blank'>
                        {}
                    </a>""".format(str(user_id), user_name)
        if isEdited:
            if not (oldMessage is None or message is None):
                message = xssFilter(message)
                oldMessage = xssFilter(oldMessage)
                message, oldMessage = compareStrings(message, oldMessage)
                oldMessage = messageBlock.format(oldMessage)
                message = messageBlock.format(message)
            elif oldMessage is None:
                oldMessage = ""
                message = messageBlock.format(xssFilter(message))
            else:
                oldMessage = messageBlock.format(xssFilter(oldMessage))
                message = ""
            if oldAttachments is not None:
                oldAttachments = attachmentsBlock.format(attachmentsParse(oldAttachments))
            else:
                oldAttachments = ""
            if oldFwd is not None:
                oldFwd = fwdBlock.format(fwdParse(oldFwd))
            else:
                oldFwd = ""
            if attachments is not None:
                attachments = attachmentsBlock.format(attachmentsParse(attachments))
            else:
                attachments = ""
            if fwd is not None:
                fwd = fwdBlock.format(fwdParse(fwd))
            else:
                fwd = ""
            messageBlock = """<td width='50%'>
                    <b>Старое</b><br />{}
                </td>
                <td width='50%'>
                    <b>Новое</b><br />{}
                </td>""".format(oldMessage+oldAttachments+oldFwd, message+attachments+fwd)
        else:
            if oldMessage is not None:
                oldMessage = messageBlock.format(xssFilter(oldMessage))
            else:
                oldMessage = ""
            if oldAttachments is not None:
                oldAttachments = attachmentsBlock.format(attachmentsParse(oldAttachments))
            else:
                oldAttachments = ""
            if oldFwd is not None:
                oldFwd = fwdBlock.format(fwdParse(oldFwd))
            else:
                oldFwd = ""
            messageBlock = """<td width='100%' colspan='2'>
                    <b>Удалено</b><br />{}
                </td>""".format(oldMessage+oldAttachments+oldFwd)
        row = row.format(message_id, peer_id, user_id, messageBlock, date)
        if os.path.exists(
            os.path.join(
                cwd,
                "mesAct",
                f"messages_{time.strftime('%d%m%y', time.localtime())}.html"
            )
        ):
            messagesActivities = open(
                os.path.join(
                    cwd,
                    "mesAct",
                    f"messages_{time.strftime('%d%m%y',time.localtime())}.html"
                ),
                'r',
                encoding='utf-8'
            )
            messagesDump = messagesActivities.read()
            messagesActivities.close()
            messagesActivities = open(
                os.path.join(
                    cwd,
                    "mesAct",
                    f"messages_{time.strftime('%d%m%y',time.localtime())}.html"
                ),
                'w',
                encoding='utf-8'
            )
        else:
            messagesDump = template
            messagesActivities = open(
                os.path.join(
                    cwd,
                    "mesAct",
                    f"messages_{time.strftime('%d%m%y',time.localtime())}.html"
                ),
                'w',
                encoding='utf-8'
            )
        messagesDump = messagesDump[:offset]+row+messagesDump[offset:]
        messagesActivities.write(messagesDump)
        messagesActivities.close()
    except TypeError:
        raise TypeError
    except BaseException:
        logger.exception("Ошибка при логгировании изменений.")

if not config['disableMessagesLogging']:
    tableWatcher = threading.Thread(target=bgWatcher)
    tableWatcher.start()
    template = """<!DOCTYPE html>
<html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="./bootstrap.css">
    </head>
    <body>
        <table class="table table-sm">
        </table>
    </body>
</html>"""
    offset = template.index("""        </table>""")
sizes = ('w', 'z', 'y', 'r', 'q', 'p', 'o', 'x', 'm', 's')
events = []
flag = threading.Event()

if config['customActions'] and config['disableMessagesLogging']:
    threading.Thread(target=eventWorker_predefinedDisabled).start()
elif not config['disableMessagesLogging'] and not config['customActions']:
    threading.Thread(target=eventWorker_customDisabled).start()
else:
    threading.Thread(target=eventWorker).start()


try:
    tryAgainIfFailed(
        main,
        maxRetries=-1
    )
except Warning:
    pass
