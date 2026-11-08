"""仅关闭本项目 3307 实例，不操作系统服务。"""
import json
from pathlib import Path
import pymysql
import ctypes
import os

root=Path(__file__).resolve().parents[1]
settings=json.loads((root/'.local/mysql-admin.json').read_text(encoding='utf-8'))
assert settings['host']=='127.0.0.1' and settings['port']==3307
handle=None
if os.name=='nt' and (root/'.local/mysql.pid').exists():
    pid=int((root/'.local/mysql.pid').read_text().strip())
    kernel=ctypes.windll.kernel32
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x00100000,False,pid)
connection=pymysql.connect(host=settings['host'],port=settings['port'],user=settings['username'],password=settings['password'],connect_timeout=5)
with connection.cursor() as cursor:
    cursor.execute('SELECT @@port')
    assert cursor.fetchone()[0]==3307
    cursor.execute('SHUTDOWN')
connection.close()
if handle:
    result=kernel.WaitForSingleObject(handle,30000)
    kernel.CloseHandle(handle)
    if result!=0:
        raise SystemExit('MySQL shutdown still pending; wait before starting again.')
print('Project MySQL shutdown completed; system MySQL80 untouched.')
