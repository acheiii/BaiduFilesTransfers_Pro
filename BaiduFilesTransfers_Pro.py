#!/usr/bin/env python
# -*- coding: utf-8 -*-
import base64
import tempfile
import threading
import time
import webbrowser
import zlib
import os
from bs4 import BeautifulSoup
import sys
import re
from lxml import etree
# noinspection PyCompatibility
from tkinter import *
import random
import requests
import urllib3
from retrying import retry

# 公共请求头
request_header = {
    'Host': 'pan.baidu.com',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
     'User_Agent' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
    'Sec-Fetch-Dest': 'document',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Sec-Fetch-Site': 'same-site',
    'Sec-Fetch-Mode': 'navigate',
    'Referer': 'https://pan.baidu.com',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7,en-GB;q=0.6,ru;q=0.5',
}
session = requests.session()
urllib3.disable_warnings()
s = requests.session()
s.trust_env = False

# 获取bdstoken函数
def get_bdstoken():
    url = 'https://pan.baidu.com/api/gettemplatevariable?clienttype=0&app_id=250528&web=1&fields=[%22bdstoken%22,%22token%22,%22uk%22,%22isdocuser%22,%22servertime%22]'
    response = s.get(url=url, headers=request_header, timeout=20, allow_redirects=True, verify=False)
    return response.json()['errno'] if response.json()['errno'] != 0 else response.json()['result']['bdstoken']

# 获取目录列表函数
def get_dir_list(bdstoken):
    url = 'https://pan.baidu.com/api/list?order=time&desc=1&showempty=0&web=1&page=1&num=1000&dir=%2F&bdstoken=' + bdstoken
    response = s.get(url=url, headers=request_header, timeout=15, allow_redirects=False, verify=False)
    return response.json()['errno'] if response.json()['errno'] != 0 else response.json()['list']


# 验证链接函数
def check_links(link_url, pass_code, bdstoken):
    # 验证提取码
    if pass_code:
        # 生成时间戳
        t_str = str(int(round(time.time() * 1000)))
        check_url = 'https://pan.baidu.com/share/verify?surl=' + link_url[25:48] + '&bdstoken=' + bdstoken + '&t=' + t_str + '&channel=chunlei&web=1&clienttype=0'
        post_data = {'pwd': pass_code, 'vcode': '', 'vcode_str': '', }
        response_post = s.post(url=check_url, headers=request_header, data=post_data, timeout=10, allow_redirects=False, verify=False)
        # 在cookie中加入bdclnd参数
        if response_post.json()['errno'] == 0:
            bdclnd = response_post.json()['randsk']
        else:
            return response_post.json()['errno']
        if bool(re.search('BDCLND=', request_header['Cookie'], re.IGNORECASE)):
            request_header['Cookie'] = re.sub(r'BDCLND=(\S+);?', r'BDCLND=' + bdclnd + ';', request_header['Cookie'])
        else:
            request_header['Cookie'] += ';BDCLND=' + bdclnd
    # 获取文件信息
    response = s.get(url=link_url, headers=request_header, timeout=15, allow_redirects=True, verify=False).content.decode("utf-8")
    shareid_list = re.findall('"shareid":(\\d+?),"', response)
    user_id_list = re.findall('"share_uk":"(\\d+?)","', response)
    fs_id_list = re.findall('"fs_id":(\\d+?),"', response)
    info_title_list = re.findall('<title>(.+)</title>', response)
    server_filedir = re.findall('"server_filename":"(.*?)",',response)
    print("--------++++++++++++++++++","link_url: ",link_url, "shareid_list: ",shareid_list,"user_id_list: ",user_id_list,"fs_id_list: ", fs_id_list,"info_title_list: ",info_title_list, "server_filename: ",server_filedir)
    if not shareid_list:
        return 1
    elif not user_id_list:
        return 2
    elif not fs_id_list:
        return info_title_list[0] if info_title_list else 3
    else:
        return [shareid_list[0], user_id_list[0], fs_id_list, server_filedir[0]]

# 获取父目录下所以子文件夹及子文件
def get_parentPath_and_subfiledir_subfile(user_id_list, shareid_list, parentPath, cookie):
    fs_id_list = []
    try:
        print("开始获取父目录")
        for page in range(1, 100):
            page = str(page)
            url = "https://pan.baidu.com/share/list?uk=" + user_id_list + "&shareid=" + shareid_list + "&order=other&desc=1&showempty=0&web=1&page=" + page + "&num=100&dir=%2F" + parentPath + "%2F"
            rsp = s.get(url=url, headers=request_header, verify=False)
            print(url)
            fs_id = re.findall('"fs_id":(\\d*)', rsp.text)
            fs_id_list.extend(fs_id)
            if rsp.status_code != 200 or ('fs_id' not in rsp.text):
                return fs_id_list
            if len(fs_id_list) > 500:
                print("转存文件数量超过500，开始递归")
                sub_file_list = get_parentPath_and_subfiledir_subfile(user_id_list, shareid_list, parentPath, cookie)
                if sub_file_list:
                    fs_id_list.extend(sub_file_list)
                break
    except Exception as e:
        print("获取父子目录出错", e)
    return fs_id_list


# 多次转存文件函数
@retry(stop_max_attempt_number=10, wait_fixed=1000)
def sub_transfer_files(shareid, user_id, bdstoken, fs_id_list, dir_name):
    url = 'https://pan.baidu.com/share/transfer?shareid=' + shareid + '&from=' + user_id + '&bdstoken=' + bdstoken + '&channel=chunlei&web=1&clienttype=0'

    fs_id = ''.join(fs_id_list)
    post_data = {'fsidlist': '[' + fs_id + ']', 'path': '/' + dir_name, }
    print(post_data, url)
    response = s.post(url=url, headers=request_header, data=post_data, timeout=25, allow_redirects=False, verify=False)
    return response.json()['errno']


# 新建目录函数
def create_dir(dir_name, bdstoken):
    url = 'https://pan.baidu.com/api/create?a=commit&bdstoken=' + bdstoken
    post_data = {'path': dir_name, 'isdir': '1', 'block_list': '[]', }
    response = s.post(url=url, headers=request_header, data=post_data, timeout=15, allow_redirects=False, verify=False)
    print(post_data)
    return response.json()['errno']

# 转存文件函数
def transfer_files(check_links_reason, dir_name, bdstoken):
    url = 'https://pan.baidu.com/share/transfer?shareid=' + check_links_reason[0] + '&from=' + check_links_reason[1] + '&bdstoken=' + bdstoken + '&channel=chunlei&web=1&clienttype=0'

    fs_id = ','.join(i for i in check_links_reason[2])
    post_data = {'fsidlist': '[' + fs_id + ']', 'path': '/' + dir_name, }
    print(post_data, url)
    response = s.post(url=url, headers=request_header, data=post_data, timeout=15, allow_redirects=False, verify=False)
    return response.json()['errno']

#检测链接种类
def check_link_type(link_list_line):
    if link_list_line.find('https://pan.baidu.com/s/') >= 0:
        link_type = '/s/'
    return link_type

# 主程序
def main():
    # 获取和初始化数据
    dir_name = "".join(input('\033[2;32m输入文件名: \033[0m\n'))
    cookie = "".join(input('\033[2;32m输入cookie: \033[0m\n'))
    request_header['Cookie'] = cookie
    link_url = "".join(input('\033[2;32m输入网盘链接: 例如https://pan.baidu.com/s/1fcW_xxxxxxxxxxxxxxx 提取码: 2ejd \n\r\r\r\t 或者 https://pan.baidu.com/s/1fcW_U-AYdXXXX-XXXX  2ejd\033[0m\n'))
    # 开始运行函数
    # 开始运行函数
    try:
        # 检查cookie输入是否正确
        if any([ord(word) not in range(256) for word in cookie]) or cookie.find('BAIDUID=') == -1:
            print('百度网盘cookie输入不正确,请检查cookie后重试.' + '\n')
            sys.exit()

        # 执行获取bdstoken
        bdstoken = get_bdstoken()
        print(bdstoken,"bdstoken-------------------------------------")
        if isinstance(bdstoken, int):
            print('没获取到bdstoken,错误代码:' + str(bdstoken) + '\n')
            sys.exit()

        # 执行获取本人网盘目录列表
        dir_list_json = get_dir_list(bdstoken)
        if type(dir_list_json) != list:
            print('没获取到网盘目录列表,请检查cookie和网络后重试.' + '\n')
            sys.exit()
        # 执行新建目录
        dir_list = [dir_json['server_filename'] for dir_json in dir_list_json]
        if dir_name and dir_name not in dir_list:
            create_dir_reason = create_dir(dir_name, bdstoken)
            if create_dir_reason != 0:
                print('文件夹名带非法字符,请改正文件夹名称后重试.' + '\n')
                sys.exit()

        # 执行转存
        # 处理http链接
        link_url = link_url.replace("http://", "https://")
        # 处理(https://pan.baidu.com/s/1tU58ChMSPmx4e3-kDx1mLg?pwd=123w)格式链接
        link_url = link_url.replace("?pwd=", " ")
        # 处理旧格式链接
        link_url = link_url.replace("https://pan.baidu.com/share/init?surl=", "https://pan.baidu.com/s/1")
        # 判断连接类型
        link_type = check_link_type(link_url)
        # 处理(https://pan.baidu.com/s/1tU58ChMSPmx4e3-kDx1mLg 123w)格式链接
        if link_type == '/s/':
            link_url_org, pass_code_org = re.sub(r'提取码*[：:](.*)', r'\1', link_url.lstrip()).split(' ', maxsplit=1)
            [link_url, pass_code] = [link_url_org.strip()[:47], pass_code_org.strip()[:4]]
            shareid_list,user_id_list,fs_id_list,server_filedir = check_links(link_url, pass_code, bdstoken)
            # 执行检查链接有效性
            check_links_reason = check_links(link_url, pass_code, bdstoken)
            # 执行转存文件
            transfer_files_reason = transfer_files(check_links_reason, dir_name, bdstoken)
            if transfer_files_reason == 0:
                print('转存成功:' + link_url + '\n')
            elif transfer_files_reason == -4:
                print('转存失败,无效登录.请退出账号在其他地方的登录:' + link_url + '\n')
            elif transfer_files_reason == 4 or transfer_files_reason == -8:
                print('转存失败,目录中已有同名文件或文件夹存在:' + link_url + '\n')
            elif transfer_files_reason == 12:
                print('转存失败,转存文件数超过限制:' + link_url + '\n', "开始分批转存......")
                #https://pan.baidu.com/share/list?uk=&shareid=&order=other&desc=1&showempty=0&web=1&page=1&num=100&dir=%2Fsecutity%2F
                print(user_id_list, shareid_list, server_filedir)
                new_fs_id_list = get_parentPath_and_subfiledir_subfile(user_id_list, shareid_list, server_filedir, cookie)
                print(new_fs_id_list)
                if new_fs_id_list != "":
                    for fs_id_list in new_fs_id_list:
                        time.sleep(round(random.uniform(0.001, 5.01), 3))
                        print(fs_id_list,"sleeptime: ",round(random.uniform(0.001, 5.01), 3))
                        sub_transfer_files(shareid_list,user_id_list, bdstoken, fs_id_list, dir_name)
            else:
                print('转存失败,错误代码(' + str(transfer_files_reason) + '):' + link_url + '\n')

        else:
            print('访问链接返回错误代码(' + str(check_links_reason) + '):' + link_url + '\n')
    except Exception as e:
        print('运行出错,请重新运行本程序.错误信息如下:' + '\n')
        print(str(e) + '\n')
        print('用户输入内容:' + '\n')
        print('百度Cookies:' + cookie + '\n')
        print('文件夹名:' + dir_name + '\n')
        print('链接输入:' + '\n' + str(link_url))
        
    # 恢复按钮状态


if __name__ == '__main__':
    main()
