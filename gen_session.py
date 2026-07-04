"""生成 Telethon User 模式所需的 SESSION_STRING。

用法：
    python gen_session.py

会读取 .env 中的 API_ID / API_HASH（没有则提示输入），随后按提示登录
（手机号含国家码，如 +8613800138000；验证码；如有两步验证再输密码），
最后打印一串 SESSION_STRING —— 填入 .env 的 SESSION_STRING= 即可启用用户模式。

注意：SESSION_STRING 等同账号凭据，务必保密，切勿分享或提交到仓库。
依赖：需已安装 telethon（pip install telethon）。
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    api_id = os.getenv('API_ID') or input('API_ID: ').strip()
    api_hash = os.getenv('API_HASH') or input('API_HASH: ').strip()

    print('\n即将登录 Telegram，请按提示输入手机号（含国家码）与验证码...\n')
    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        session_string = client.session.save()
        print('\n' + '=' * 60)
        print(f'登录成功：{me.first_name} (id={me.id})')
        print('把下面这行填入 .env 的 SESSION_STRING=（务必保密）：')
        print('-' * 60)
        print(session_string)
        print('=' * 60)


if __name__ == '__main__':
    main()
