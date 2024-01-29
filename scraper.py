import asyncio
import logging
import os
import re
import ssl
import subprocess
import time
from datetime import datetime

import aiohttp
import asyncpg
import schedule
from asyncpg import PostgresError
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException


async def fetch_car_data(session, car_url, browser, db_params):
    try:
        async with session.get(car_url) as response:
            response.raise_for_status()
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')

            data = {}

            title_element = soup.select_one('.head')
            if title_element:
                title = title_element.get('title', 'No title found')

            price_element = soup.select_one('.price_value strong')
            if price_element:
                price_text = price_element.text.strip()
                price_cleaned = re.sub(r'\D', '', price_text)
            else:
                price_cleaned = None

            odometer_element = soup.select_one('.base-information span')
            if odometer_element:
                odometer_text = odometer_element.text.strip()
            else:
                odometer_text = None

            username_element = soup.select_one('.seller_info_name')
            if username_element:
                username = username_element.text.strip()
            elif username_element is None:
                username = 'None'

            image_element = soup.select_one('.outline')['src']
            if image_element:
                image_url = image_element
            else:
                image_url = 'None'

            images_count_element = soup.select_one('.show-all')
            if images_count_element:
                images_count_text = images_count_element.text.strip()
                images_count = re.sub(r'\D', '', images_count_text)
            else:
                images_count = None

            car_num_element = soup.select_one('.state-num')
            if car_num_element:
                car_num = car_num_element.text.strip()
                car_num = car_num.replace('Мы распознали гос.номер авто на фото и проверили его по реестрам МВД.', '').strip()
            else:
                car_num = 'None'

            car_vin_element = soup.select_one('.label-vin')
            if car_vin_element:
                car_vin = car_vin_element.text.strip()
            else:
                car_vin = 'None'

            try:
                browser.get(car_url)

                try:
                    max_attempts = 3
                    attempts = 0

                    while attempts < max_attempts:
                        time.sleep(0.85)

                        phone_button = None
                        phone_numbers = []
                        phone_elements = None

                        try:
                            overlay = browser.find_element(By.CSS_SELECTOR, '.fc-dialog-overlay')
                            if overlay.is_displayed():
                                button = WebDriverWait(browser, 10).until(
                                    EC.element_to_be_clickable((By.CLASS_NAME, 'fc-cta-do-not-consent'))
                                )
                                button.click()
                                time.sleep(1)
                        except Exception:
                            logger.debug(f"Can not found overlay element")

                        try:
                            time.sleep(1)
                            phone_button = WebDriverWait(browser, 10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, '.phone_show_link'))
                            )
                        except TimeoutException:
                            logger.warning("The phone button is not found within the time specified")

                        if phone_button is not None:
                            browser.execute_script("arguments[0].scrollIntoView();", phone_button)

                            try:
                                phone_button.click()
                            except ElementClickInterceptedException:
                                try:
                                    overlay = browser.find_element(By.CSS_SELECTOR, '.fc-dialog-overlay')
                                    if overlay.is_displayed():
                                        button = WebDriverWait(browser, 10).until(
                                            EC.element_to_be_clickable((By.CLASS_NAME, 'fc-cta-do-not-consent'))
                                        )
                                        button.click()
                                        time.sleep(1)

                                    phone_button.click()
                                except Exception as e:
                                    logger.error(f"An error occurred while click on overlay | {e}")
                            time.sleep(0.85)

                        try:
                            phone_elements = WebDriverWait(browser, 10).until(
                                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '.popup-successful-call-desk'))
                            )
                        except Exception as e:
                            logger.error(f"An error occurred while search phone numbers data | {e}")

                        if not phone_elements:
                            logger.warning("No items were found for obtaining phone numbers")

                        phone_numbers_found = False

                        if phone_elements:
                            for phone_element in phone_elements:
                                phone_number_raw = phone_element.text
                                phone_number = re.sub(r'\D', '', phone_number_raw)
                                if phone_number:
                                    phone_numbers.append(int(phone_number))
                                    phone_numbers_found = True

                        data['phone_numbers'] = phone_numbers

                        if phone_numbers_found:
                            break
                        else:
                            attempts += 1
                            logger.warning(f"Attempt {attempts}/{max_attempts}: No phone numbers found, retrying after 3 seconds")
                            await asyncio.sleep(3)

                    if attempts == max_attempts:
                        logger.warning("Maximum attempts reached. No phone numbers found.")
                except Exception as e:
                    logger.error(f"An error occurred while fetching phone numbers | {e}")
                    data['phone_numbers'] = phone_numbers[0]
            except TimeoutException:
                logger.warning('Timeout waiting for phone number to appear')

            data.update({
                'url': car_url,
                'title': title,
                'price_usd': int(price_cleaned) if price_cleaned else 0,
                'odometer': int(odometer_text) * 1000 if odometer_text else 0,
                'username': username,
                'image_url': image_url,
                'images_count': int(images_count) if images_count else 0,
                'car_num': car_num,
                'car_vin': car_vin,
                'datetime_found': datetime.now()
            })

            await save_to_database(data, db_params)
    except Exception as e:
        logger.error(f"An error occurred while fetching car data | {e}")


async def fetch_car_urls(session, start_url):
    try:
        async with session.get(start_url) as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')

            car_sections = soup.select('.ticket-item')
            if car_sections:
                car_urls = [section.select_one('.content-bar a')['href'] for section in car_sections]
            else:
                car_urls = None

            return car_urls
    except Exception as e:
        logger.info(f"An error occurred while fetching car urls from {start_url} | {e}")


async def scrape_auto_data(browser, db_params, dump_command):
    try:
        logger.info("Starting scraping auto data")
        await asyncio.sleep(5)

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        start_url = 'https://auto.ria.com/car/used/?page={}'

        wait = WebDriverWait(browser, 4)

        current_page = 1

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
            while True:
                now = datetime.now()
                if now.hour == 00 and now.minute == 0 or now.minute == 1:
                    await create_dump(dump_command)
                    logger.info("Create dump file")

                car_urls = await fetch_car_urls(session, start_url.format(current_page))
                if car_urls is not None:

                    await asyncio.gather(*[fetch_car_data(session, car_url, browser, db_params) for car_url in car_urls])

                    try:
                        logger.info(f"Navigating to the next page ({current_page + 1})")
                        current_page += 1

                        try:
                            wait.until(lambda browser: browser.execute_script("return document.readyState") == "complete")
                        except TimeoutException:
                            logger.warning("Timeout waiting for page to load")

                        try:
                            location_popup = browser.find_element(By.CSS_SELECTOR, '.your-location-popup-selector')
                            if location_popup.is_displayed():
                                location_popup.find_element(By.CSS_SELECTOR, '.close-button-selector').click()
                        except NoSuchElementException:
                            pass
                    except TimeoutException:
                        logger.warning("No more pages")
                        break
                    except StaleElementReferenceException:
                        logger.warning("Element is stale, continuing to the next iteration")
                else:
                    break
    except Exception as e:
        logger.error(f"An error occurred while scraping auto data | {e}")


async def save_to_database(data, db_params):
    max_attempts = 3
    current_attempt = 0
    connection = None

    while current_attempt < max_attempts:
        try:
            connection = await asyncpg.connect(**db_params)
            logger.info(f"success create connection with database")

            await create_table(connection, data)

            insert_query = """INSERT INTO data_car (url, title, price_usd, datetime_found, odometer, username, image_url, images_count, 
            car_num, car_vin, phone_numbers) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) """
            await connection.execute(
                insert_query,
                data['url'],
                data['title'],
                data['price_usd'],
                data['datetime_found'],
                data['odometer'],
                data['username'],
                data['image_url'],
                data['images_count'],
                data['car_num'],
                data['car_vin'],
                str(data['phone_numbers'])
            )

            logger.info(f"Data saved to database successfully for {data['url']}")
            break
        except PostgresError as e:
            logger.error(f"An error occurred while saving to the database | {e}", exc_info=True)
            current_attempt += 1
            logger.warning(f"Attempt {current_attempt}/{max_attempts}: Retrying after 3 seconds")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"An error occurred while save to database | {e}", exc_info=True)
        finally:
            if connection:
                await connection.close()


async def create_table(cursor, data):
    try:
        create_table_query = """
            CREATE TABLE IF NOT EXISTS data_car (
                id SERIAL PRIMARY KEY,
                url VARCHAR(255),
                title VARCHAR(255),
                price_usd INTEGER,
                odometer INTEGER,
                username VARCHAR(255),
                image_url VARCHAR(255),
                images_count INTEGER,
                car_num VARCHAR(255),
                car_vin VARCHAR(255),
                phone_numbers VARCHAR(255),
                datetime_found TIMESTAMP
            )
            """
        await cursor.execute(create_table_query)

        logger.info(f"Table created successfully for {data['url']}")
    except Exception as e:
        logger.error(f"An error occurred while create table | {e}")


async def create_dump(dump_command):
    try:
        os.makedirs("dumps", exist_ok=True)

        os.environ['PGPASSWORD'] = '123456789'

        await asyncio.to_thread(subprocess.run, dump_command, check=True)

        del os.environ['PGPASSWORD']
    except Exception as e:
        logger.error(f"An error occurred while create dump | {e}")


async def scrape_auto_data_wrapper(browser, db_params, dump_command):
    await scrape_auto_data(browser, db_params, dump_command)


def schedule_scrape_auto_data(browser, db_params, dump_command):
    loop = asyncio.get_event_loop()
    loop.create_task(scrape_auto_data_wrapper(browser, db_params, dump_command))


async def main():
    browser = None

    db_params = {
        'host': 'postgres',
        'database': 'scraping',
        'user': 'user_scraping',
        'password': '123456789'
    }

    dump_file_path = f"dumps/dump_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
    dump_command = [
        'pg_dump',
        '--host', db_params['host'],
        '--dbname', db_params['database'],
        '--username', db_params['user'],
        '--file', dump_file_path
    ]

    while True:
        logger.info('start new iteration')

        try:
            local_launch = os.getenv("LOCAL_LAUNCH", "False").lower() == "true"

            """
                FOR DOCKER COMPOSE LAUNCH
            """
            if not local_launch:
                time.sleep(30)
                command_executor = "http://selenium-hub:4444/wd/hub"
                options = webdriver.FirefoxOptions()
                browser = webdriver.Remote(command_executor=command_executor, options=options)
                time.sleep(10)
                logger.info("success connect to remote browser")

                schedule.every().day.at("12:00").do(schedule_scrape_auto_data, browser, db_params, dump_command)

                while True:
                    schedule.run_pending()
                    await asyncio.sleep(1)
            """
                FOR DOCKER COMPOSE LAUNCH
            """

            """
                FOR LOCAL LAUNCH
            """
            if local_launch:
                db_params = {
                    'host': 'localhost',
                    'database': 'scraping',
                    'user': 'user_scraping',
                    'password': '123456789'
                }

                dump_file_path = f"dumps/dump_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
                dump_command = [
                    '/opt/homebrew/Cellar/postgresql@15/15.5_3/bin/pg_dump',
                    '--host', db_params['host'],
                    '--dbname', db_params['database'],
                    '--username', db_params['user'],
                    '--file', dump_file_path
                ]

                options = webdriver.ChromeOptions()
                options.add_argument('--headless')
                browser = webdriver.Chrome(options=options)
                logger.info("success connect to local browser")

                await scrape_auto_data(browser, db_params, dump_command)
            """
                FOR LOCAL LAUNCH
            """

        except Exception as e:
            logger.error(f"An error occurred from main | {e}")
        finally:
            try:
                browser.quit()
            except Exception as e:
                logger.error(f"An error occurred while closing the browser | {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    logger = logging.getLogger(__name__)

    asyncio.get_event_loop().run_until_complete(main())
