import pytz
import time
import requests
import threading
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional
from urllib.parse import urljoin
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.core.event import eventmanager
from app.db.site_oper import SiteOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.timer import TimerUtils

class lemonshengyou(_PluginBase):
    # 插件名称
    plugin_name = "柠檬站点神游"
    # 插件描述
    plugin_desc = "自动完成柠檬站点每日免费神游三清天，获取奖励。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/firebat1314/moviepilot-plugins/main/icons/lemon.ico"
    # 插件版本
    plugin_version = "1.0.5"
    # 插件作者
    plugin_author = "firebat1314"
    # 作者主页
    author_url = "https://github.com/firebat1314"
    # 插件配置项ID前缀
    plugin_config_prefix = "lemonshengyou_"
    # 加载顺序
    plugin_order = 0
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    sites: SitesHelper = None
    siteoper: SiteOper = None
    
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _onlyonce: bool = False
    _notify: bool = False
    _retry_count: int = 3
    _retry_interval: int = 5
    _history_days: int = 7
    _lemon_site: str = None
    _lock: Optional[threading.Lock] = None
    _running: bool = False

    def init_plugin(self, config: Optional[dict] = None):
        self._lock = threading.Lock()
        self.sites = SitesHelper()
        self.siteoper = SiteOper()

        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = bool(config.get("enabled", False))
            self._cron = str(config.get("cron", ""))
            self._onlyonce = bool(config.get("onlyonce", False))
            self._notify = bool(config.get("notify", False))
            self._retry_count = int(config.get("retry_count", 3))
            self._retry_interval = int(config.get("retry_interval", 5))
            self._history_days = int(config.get("history_days", 7))
            self._lemon_site = config.get("lemon_site")

            # 保存配置
            self.__update_config()

        # 加载模块
        if self._enabled or self._onlyonce:
            # 立即运行一次
            if self._onlyonce:
                try:
                    # 定时服务
                    self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                    logger.info("柠檬神游服务启动，立即运行一次")
                    self._scheduler.add_job(func=self.do_shenyou, trigger='date',
                                         run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                         name="柠檬神游服务")

                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.__update_config()

                    # 启动任务
                    if self._scheduler and self._scheduler.get_jobs():
                        self._scheduler.print_jobs()
                        self._scheduler.start()
                except Exception as e:
                    logger.error(f"启动一次性任务失败: {str(e)}")

    def __update_config(self):
        """
        更新配置
        """
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "cron": self._cron,
            "onlyonce": self._onlyonce,
            "retry_count": self._retry_count,
            "retry_interval": self._retry_interval,
            "history_days": self._history_days,
            "lemon_site": self._lemon_site
        })

    def get_state(self) -> bool:
        return self._enabled

    def get_command(self) -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        if self._enabled and self._cron:
            try:
                # 检查是否为5位cron表达式
                if str(self._cron).strip().count(" ") == 4:
                    return [{
                        "id": "LemonShenYou",
                        "name": "柠檬神游服务",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "func": self.do_shenyou,
                        "kwargs": {}
                    }]
                else:
                    logger.error("cron表达式格式错误")
                    return []
            except Exception as err:
                logger.error(f"定时任务配置错误：{str(err)}")
                return []
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        # 获取支持的站点列表
        site_options = []
        for site in self.sites.get_indexers():
            if not site.get("public"):
                site_name = site.get("name", "")
                if "柠檬" in site_name:
                    site_options.append({
                        "title": site_name,
                        "value": site.get("id")
                    })
        
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'lemon_site',
                                            'label': '选择站点',
                                            'items': site_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'retry_count',
                                            'label': '最大重试次数',
                                            'type': 'number',
                                            'placeholder': '3'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'retry_interval',
                                            'label': '重试间隔(秒)',
                                            'type': 'number',
                                            'placeholder': '5'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'history_days',
                                            'label': '历史保留天数',
                                            'type': 'number',
                                            'placeholder': '7'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '【使用说明】\n1. 选择要进行神游的柠檬站点\n2. 设置执行周期，建议每天早上8点执行 (0 8 * * *)\n3. 可选择开启通知，在神游后收到结果通知\n4. 可以设置重试次数和间隔，以及历史记录保留天数\n5. 启用插件并保存即可'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": False,
            "cron": "0 8 * * *",
            "onlyonce": False,
            "retry_count": 3,
            "retry_interval": 5,
            "history_days": 7,
            "lemon_site": None
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """退出插件"""
        try:
            if self._scheduler:
                if self._lock and hasattr(self._lock, 'locked') and self._lock.locked():
                    logger.info("等待当前任务执行完成...")
                    try:
                        self._lock.acquire()
                        self._lock.release()
                    except:
                        pass
                if hasattr(self._scheduler, 'remove_all_jobs'):
                    self._scheduler.remove_all_jobs()
                if hasattr(self._scheduler, 'running') and self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{str(e)}")

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event):
        """
        删除对应站点选中
        """
        site_id = event.event_data.get("site_id")
        if site_id and str(site_id) == str(self._lemon_site):
            self._lemon_site = None
            self._enabled = False
            # 保存配置
            self.__update_config()

    def do_shenyou(self):
        """
        执行神游
        """
        if not self._lock:
            self._lock = threading.Lock()
            
        if not self._lock.acquire(blocking=False):
            logger.debug("已有任务正在执行，本次调度跳过！")
            return
            
        try:
            self._running = True
            
            # 获取站点信息
            if not self._lemon_site:
                logger.error("未配置柠檬站点！")
                return
                
            site_info = None
            for site in self.sites.get_indexers():
                if str(site.get("id")) == str(self._lemon_site):
                    site_info = site
                    break
                    
            if not site_info:
                logger.error("未找到配置的柠檬站点信息！")
                return
                
            # 执行神游
            success = False
            error_msg = None
            rewards = []
            
            for i in range(self._retry_count):
                try:
                    success, error_msg, rewards = self.__do_shenyou(site_info)
                    if success:
                        break
                    if i < self._retry_count - 1:
                        logger.warning(f"第{i+1}次神游失败：{error_msg}，{self._retry_interval}秒后重试")
                        time.sleep(self._retry_interval)
                except Exception as e:
                    error_msg = str(e)
                    if i < self._retry_count - 1:
                        logger.warning(f"第{i+1}次神游出错：{error_msg}，{self._retry_interval}秒后重试")
                        time.sleep(self._retry_interval)
            
            # 发送通知
            if self._notify:
                title = "🌈 柠檬神游任务"
                text = f"站点：{site_info.get('name')}\n"
                if success:
                    text += "状态：✅ 神游成功\n"
                else:
                    text += f"状态：❌ 神游失败\n原因：{error_msg}"
                
                if rewards:
                    text += "\n🎁 获得奖励：\n"
                    for reward in rewards:
                        text += f"- {reward}\n"
                
                text += f"\n⏱️ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
                
                self.post_message(
                    mtype=NotificationType.SiteMessage,
                    title=title,
                    text=text
                )
                
        except Exception as e:
            logger.error(f"神游任务执行出错：{str(e)}")
        finally:
            self._running = False
            if self._lock and hasattr(self._lock, 'locked') and self._lock.locked():
                try:
                    self._lock.release()
                except RuntimeError:
                    pass
            logger.debug("任务执行完成")

    def __do_shenyou(self, site_info: CommentedMap) -> Tuple[bool, Optional[str], List[str]]:
        """
        执行神游操作
        :return: (是否成功, 错误信息, 奖励列表)
        """
        site_name = site_info.get("name", "").strip()
        site_url = site_info.get("url", "").strip()
        site_cookie = site_info.get("cookie", "").strip()
        ua = site_info.get("ua", "").strip()
        proxies = settings.PROXY if site_info.get("proxy") else None

        if not all([site_name, site_url, site_cookie, ua]):
            return False, "站点信息不完整", []

        # 构建请求Session
        session = requests.Session()
        
        # 配置重试
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[403, 404, 500, 502, 503, 504],
            allowed_methods=frozenset(['GET', 'POST']),
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        # 设置请求头
        session.headers.update({
            'User-Agent': ua,
            'Cookie': site_cookie,
            'Referer': site_url
        })
        
        if proxies:
            session.proxies = proxies
            
        try:
            # 获取用户名
            username = self.__get_username(session, site_info)
            if not username:
                logger.error("无法获取用户名，请检查站点Cookie是否有效")
                return False, "无法获取用户名", []
            
            logger.info(f"获取到用户名: {username}")
            
            # 获取今天的日期，用于查找当天的记录
            today = datetime.now().strftime('%Y-%m-%d')
            
            # 1. 访问神游页面
            lottery_url = urljoin(site_url, "lottery.php")
            logger.info(f"访问神游页面: {lottery_url}")
            response = session.get(lottery_url, timeout=(5, 15))
            response.raise_for_status()
            
            # 使用BeautifulSoup解析页面
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 函数：查找用户的神游记录，检查前MAX_RECORDS条记录
            def find_user_lottery_records(soup_obj, max_records=200):
                records = []
                lottery_list = soup_obj.find('div', class_='lottery_list')
                if not lottery_list:
                    logger.warning("页面中未找到神游记录列表")
                    return records
                
                items = lottery_list.find_all('div', class_='item')
                logger.info(f"找到 {len(items)} 条神游记录")
                
                # 只检查前max_records条记录
                check_items = items[:max_records] if len(items) > max_records else items
                
                # 记录用于匹配的用户名格式
                logger.info(f"要匹配的用户名: '{username}'")
                
                for item in check_items:
                    # 查找日期
                    date_span = item.find('span', class_='date')
                    item_date = date_span.get_text().strip() if date_span else ""
                    
                    # 查找用户链接
                    user_link = item.find('a', class_=['User_Name', 'PowerUser_Name', 'EliteUser_Name', 'CrazyUser_Name', 'InsaneUser_Name', 'VIP_Name', 'Uploader_Name'])
                    
                    # 提取记录原始文本用于调试
                    item_text = item.get_text(strip=True)
                    
                    # 严格匹配用户名
                    is_user_record = False
                    if user_link:
                        # 方法1: 直接检查链接文本与用户名是否完全匹配
                        link_text = user_link.get_text(strip=True)
                        if link_text == username:
                            is_user_record = True
                            logger.info(f"方法1匹配成功: 链接文本'{link_text}'与用户名'{username}'完全匹配")
                        
                        # 方法2: 检查span的title属性是否与用户名完全匹配
                        span = user_link.find('span')
                        if span and span.has_attr('title') and span['title'] == username:
                            is_user_record = True
                            logger.info(f"方法2匹配成功: span的title属性'{span['title']}'与用户名匹配")
                        
                        # 方法3: 检查是否包含userdetails.php链接和用户ID
                        if user_link.has_attr('href') and 'userdetails.php?id=' in user_link['href']:
                            user_id = user_link['href'].split('userdetails.php?id=')[1].split('&')[0]
                            # 记录ID以便后续处理
                            logger.debug(f"记录中的用户ID: {user_id}")
                            # 这里我们无法直接匹配ID，因为需要知道当前用户ID
                    
                    if is_user_record:
                        # 找到用户记录
                        reward_text = item.get_text(strip=True)
                        # 提取奖励部分，格式通常是: [日期] [用户名] - [奖励内容]
                        reward_parts = reward_text.split('-')[-1].strip() if '-' in reward_text else reward_text
                        
                        # 只保留包含神游关键词的记录
                        if '【神游' in reward_parts:
                            logger.info(f"✅ 匹配成功 - 确认是用户 '{username}' 的记录: {reward_parts} ({item_date})")
                            records.append((reward_parts, item_date))
                    else:
                        # 记录不匹配的原因，用于调试
                        logger.debug(f"不匹配记录: {item_text[:30]}...")
                
                if not records:
                    logger.warning(f"未找到用户 '{username}' 的任何神游记录! 检查了 {len(check_items)} 条记录")
                else:
                    logger.info(f"共找到 {len(records)} 条用户 '{username}' 的神游记录")
                
                return records
            
            # 先查找已有的神游记录
            user_records = find_user_lottery_records(soup)
            
            # 查找今日记录
            today_records = [record for record, date in user_records if today in date]
            
            # 查找按钮状态
            free_button = None
            button_disabled = False
            
            for form in soup.find_all('form', {'action': '?', 'method': 'post'}):
                type_input = form.find('input', {'name': 'type', 'value': '0'})
                if type_input:
                    button = form.find('button')
                    if button and '免费' in button.get_text():
                        free_button = form
                        button_disabled = button.has_attr('disabled')
                        logger.info(f"找到免费神游按钮，状态: {'禁用' if button_disabled else '可用'}")
                        break
            
            # 如果按钮被禁用，说明今天已经参与过了
            if button_disabled:
                logger.info("今天已经神游过")
                # 如果找到了今天的记录，返回记录内容
                if today_records:
                    reward = today_records[0][0]
                    return False, "今天已经神游过", [reward]
                # 如果有历史记录，至少返回最近的一条
                elif user_records:
                    reward = user_records[0][0]
                    return False, "今天已经神游过", [reward]
                # 没有找到任何记录
                else:
                    return False, "今天已经神游过，但未找到属于当前用户的奖励记录", []
            
            # 如果没有找到免费按钮
            if not free_button:
                logger.error("未找到免费神游按钮")
                return False, "未找到神游按钮", []
            
            # 2. 执行神游
            logger.info("执行神游操作...")
            shenyou_data = {
                "type": "0"  # 0 表示免费神游
            }
            
            response = session.post(lottery_url, data=shenyou_data, timeout=(5, 15))
            response.raise_for_status()
            
            # 等待服务器处理，确保记录已更新
            time.sleep(2)
            
            # 重新获取页面，查看最新结果
            logger.info("重新获取神游页面，查找结果...")
            response = session.get(lottery_url, timeout=(5, 15))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找最新的神游记录
            new_user_records = find_user_lottery_records(soup)
            
            # 查找今日新记录
            new_today_records = [record for record, date in new_user_records if today in date]
            
            # 重新检查按钮状态
            button_now_disabled = False
            for form in soup.find_all('form', {'action': '?', 'method': 'post'}):
                type_input = form.find('input', {'name': 'type', 'value': '0'})
                if type_input:
                    button = form.find('button')
                    if button and '免费' in button.get_text():
                        button_now_disabled = button.has_attr('disabled')
                        logger.info(f"神游后按钮状态: {'禁用' if button_now_disabled else '可用'}")
                        break
            
            # 检查神游是否成功
            # 1. 如果按钮从可用变为禁用，这是最明确的神游成功标志
            if not button_disabled and button_now_disabled:
                if new_user_records:
                    reward = new_user_records[0][0]
                    logger.info(f"神游成功，按钮已禁用，获得奖励: {reward}")
                    return True, None, [reward]
                else:
                    # 按钮状态变化但未找到记录，仍然视为成功
                    logger.info("神游成功，按钮已禁用，但未找到奖励记录")
                    return True, None, ["神游成功，但未找到具体奖励信息"]
            
            # 2. 如果新增了今日记录，表示神游成功
            if len(new_today_records) > len(today_records):
                reward = new_today_records[0][0]
                logger.info(f"神游成功，获得奖励: {reward}")
                return True, None, [reward]
            
            # 3. 检查页面中是否有成功提示
            success_msg = soup.find('div', class_='success')
            if success_msg:
                if new_user_records:
                    reward = new_user_records[0][0]
                    logger.info(f"神游成功，页面有成功提示，获得奖励: {reward}")
                    return True, None, [reward]
                else:
                    logger.info("神游成功，页面有成功提示，但未找到奖励记录")
                    return True, None, ["神游成功，但未找到具体奖励信息"]
            
            # 4. 如果有今日记录，即使没有其他明确标志，也视为可能成功
            if new_today_records:
                reward = new_today_records[0][0]
                logger.info(f"找到今日神游记录，视为成功，奖励: {reward}")
                return True, None, [reward]
            
            # 5. 如果有任何用户记录，但确实无法判断成功与否
            if new_user_records:
                reward = new_user_records[0][0]
                logger.warning(f"找到用户神游记录，但无法确认是否为本次操作: {reward}")
                # 这里改为返回成功，因为有记录就说明神游过
                return True, "找到神游记录，但无法确认是否为本次操作", [reward]
            
            # 查看页面提示信息
            alert_msg = ""
            alerts = soup.find_all('div', class_=['error', 'success', 'notice', 'alert'])
            for alert in alerts:
                alert_text = alert.get_text(strip=True)
                if alert_text:
                    alert_msg = alert_text
                    logger.info(f"页面提示信息: {alert_msg}")
                    break
                    
            if alert_msg:
                if "成功" in alert_msg:
                    return True, f"神游成功: {alert_msg}", []
                else:
                    return False, f"神游结果: {alert_msg}", []
            
            # 真的找不到任何奖励记录
            logger.error(f"神游后未找到用户 '{username}' 的任何奖励记录")
            return False, f"神游操作完成，但未找到属于用户 '{username}' 的奖励记录", []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {str(e)}")
            return False, f"请求失败: {str(e)}", []
        except Exception as e:
            logger.error(f"神游失败: {str(e)}")
            return False, f"神游失败: {str(e)}", []
        finally:
            session.close()
            
    def __get_username(self, session, site_info: CommentedMap) -> str:
        """
        获取用户名
        :param session: 请求会话
        :param site_info: 站点信息
        :return: 用户名
        """
        site_url = site_info.get("url", "").strip()
        
        try:
            # 访问个人信息页面
            usercp_url = urljoin(site_url, "/usercp.php")
            response = session.get(
                usercp_url,
                timeout=(3.05, 10)
            )
            response.raise_for_status()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 尝试多种方式获取用户名
            username = None
            
            # 方法1: 从欢迎信息中获取
            welcome_msg = soup.select_one('.welcome')
            if welcome_msg:
                text = welcome_msg.get_text()
                import re
                username_match = re.search(r'欢迎回来.*?([^,，\s]+)', text)
                if username_match:
                    username = username_match.group(1)
            
            # 方法2: 从用户详情链接中获取
            if not username:
                username_elem = soup.select_one('a[href*="userdetails.php"]')
                if username_elem:
                    username = username_elem.get_text(strip=True)
            
            # 方法3: 直接尝试查找用户名元素
            if not username:
                # 尝试找到常见的用户名显示位置
                user_elements = soup.select('.username, .user, .profile-username, a[href*="userdetails"]')
                for elem in user_elements:
                    potential_username = elem.get_text(strip=True)
                    if potential_username and len(potential_username) > 1 and len(potential_username) < 30:
                        username = potential_username
                        break
            
            return username
        except Exception as e:
            logger.warning(f"获取用户名失败: {str(e)}")
            return None 