import os
import time
import signal
import sys
import requests
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchWindowException, InvalidSessionIdException

driver = None
downloaded_urls = set()

def signal_handler(sig, frame):
    print("\n正在关闭浏览器并退出...")
    if driver:
        try:
            driver.quit()
        except:
            pass
    sys.exit(0)

def ensure_picture_folder():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    picture_folder = os.path.join(desktop, "picture")
    os.makedirs(picture_folder, exist_ok=True)
    print(f"图片将保存到: {picture_folder}")
    return picture_folder

def inject_click_listener(driver):
    inject_script = """
    if (!window.clickListenerAdded) {
        window.clickListenerAdded = true;
        document.addEventListener('click', function(e) {
            let target = e.target;
            let info = {
                timestamp: Date.now(),
                tag: target.tagName,
                id: target.id || null,
                class: target.className || null,
                text: target.innerText ? target.innerText.slice(0, 100) : null,
                href: target.href || target.getAttribute('href') || null,
                src: target.src || target.getAttribute('src') || null,
                selector: getSelector(target)
            };
            let clicks = JSON.parse(localStorage.getItem('clicked_elements') || '[]');
            clicks.push(info);
            localStorage.setItem('clicked_elements', JSON.stringify(clicks));
        });

        function getSelector(el) {
            if (el.id) return '#' + el.id;
            let selector = el.tagName.toLowerCase();
            if (el.className && typeof el.className === 'string') {
                selector += '.' + el.className.split(' ').join('.');
            }
            return selector;
        }
    }
    """
    try:
        driver.execute_script(inject_script)
    except Exception as e:
        print(f"注入脚本失败: {e}")

def download_image(img_url, save_folder, window_handle=None, force=False):
    """下载图片，返回保存路径或None，输出详细信息"""
    global downloaded_urls
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    if not force and img_url in downloaded_urls:
        print(f"[{timestamp}] 图片已下载过，跳过: {img_url}")
        return None

    print(f"[{timestamp}] 开始下载图片: {img_url}")

    try:
        ext = os.path.splitext(img_url.split('?')[0])[1]
        if not ext or ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            ext = '.jpg'
        suffix = f"_{window_handle[-6:]}" if window_handle else ""
        file_name = f"img_{timestamp}{suffix}{ext}"
        save_path = os.path.join(save_folder, file_name)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Referer': driver.current_url if driver else ''
        }
        response = requests.get(img_url, headers=headers, timeout=15)
        response.raise_for_status()

        with open(save_path, 'wb') as f:
            f.write(response.content)

        downloaded_urls.add(img_url)
        print(f"[{timestamp}] 下载成功！文件已保存至: {save_path}")
        return save_path

    except requests.exceptions.RequestException as e:
        print(f"[{timestamp}] 下载失败（网络错误）: {e}")
    except Exception as e:
        print(f"[{timestamp}] 下载失败（未知错误）: {e}")

    return None

def process_new_window(driver, selector, save_folder, window_handle):
    try:
        driver.switch_to.window(window_handle)
        inject_click_listener(driver)

        img_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        time.sleep(1)
        img_url = img_element.get_attribute('src')
        if not img_url:
            print(f"窗口 {window_handle} 图片src为空")
            return False

        if not img_url.startswith(('http://', 'https://', 'data:')):
            base_url = driver.current_url
            img_url = urljoin(base_url, img_url)

        result = download_image(img_url, save_folder, window_handle)
        if result:
            print(f"窗口检测下载返回: {result}")
        return bool(result)
    except TimeoutException:
        print(f"窗口 {window_handle} 超时：未找到图片元素")
    except NoSuchWindowException:
        print(f"窗口 {window_handle} 已关闭")
    except Exception as e:
        print(f"处理窗口 {window_handle} 时出错: {e}")
    return False

def main():
    global driver
    signal.signal(signal.SIGINT, signal_handler)

    css_selector = "app-applypoint .container .list li img.fjtp"
    start_url = input("请输入起始平台URL: ").strip()
    picture_folder = ensure_picture_folder()

    driver = webdriver.Firefox()
    driver.get(start_url)
    inject_click_listener(driver)
    print("浏览器已启动。监控中... 按 Ctrl+C 停止。")

    processed_handles = set()
    processed_handles.add(driver.current_window_handle)

    try:
        while True:
            # 检测新窗口
            try:
                current_handles = driver.window_handles
            except InvalidSessionIdException:
                print("浏览器会话已失效，退出程序。")
                break
            except Exception as e:
                print(f"获取窗口句柄失败: {e}")
                time.sleep(1)
                continue

            new_handles = [h for h in current_handles if h not in processed_handles]
            for handle in new_handles:
                print(f"检测到新窗口: {handle}")
                process_new_window(driver, css_selector, picture_folder, handle)
                processed_handles.add(handle)

            # 收集点击记录
            current_handle = driver.current_window_handle
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    clicks = driver.execute_script(
                        "return JSON.parse(localStorage.getItem('clicked_elements') || '[]');"
                    )
                    if clicks:
                        for click in clicks:
                            ts = time.strftime("%Y%m%d_%H%M%S")
                            print(f"[{ts}] 点击内容: {click}")

                            # 下载条件：是图片且有src
                            tag = click.get('tag', '').upper()
                            img_url = click.get('src')
                            if tag == 'IMG' and img_url:
                                # 可选：只处理包含fjtp类的图片，放开注释即可
                                # class_attr = click.get('class', '')
                                # if 'fjtp' not in class_attr:
                                #     continue
                                if not img_url.startswith(('http://', 'https://', 'data:')):
                                    base_url = driver.current_url
                                    img_url = urljoin(base_url, img_url)
                                print(f"[{ts}] 触发点击下载: {img_url}")
                                result = download_image(img_url, picture_folder, handle)
                                if result:
                                    print(f"点击下载返回: {result}")
                                else:
                                    print(f"点击下载失败，返回值为 None")

                        # 清空已处理的记录（确保即使有异常也尝试删除）
                        try:
                            driver.execute_script("localStorage.removeItem('clicked_elements');")
                        except Exception as e:
                            print(f"清空localStorage失败: {e}")
                except NoSuchWindowException:
                    # 窗口已关闭，忽略
                    pass
                except Exception as e:
                    print(f"处理窗口 {handle} 时出错: {e}")

            # 恢复当前窗口
            try:
                driver.switch_to.window(current_handle)
            except:
                pass

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

if __name__ == "__main__":
    main()