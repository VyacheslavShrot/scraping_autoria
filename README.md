# <strong>Scraping AutoRia Web Site</strong>

- This project shows for the most part my work with asynchronous programming and database, and scraping technologies. I did the project in a fast mode, so there are some shortcomings)

# Structure

- scraping of used car data from https://auto.ria.com/car/used/
- scraping with <strong style="color:green">Selenium</strong> and <strong style="color:green">BeautifulSoup</strong>
- all code is written in <strong style="color:green">Asynchronous Programming</strong>
- used saving data to a <strong style="color:green">PostgreSQL</strong> database
- <strong style="color:green">daily run</strong> and <strong style="color:green">dump file</strong> creation

# <strong>Local Launch</strong><br>
- need to set <strong style="color:green">LOCAL_LAUNCH=True</strong> in the env file<br>
- must have <strong style="color:green">Chrome</strong> installed as a scraping browser


# <strong>Launch in Docker-Compose</strong><br>
- need to run <strong style="color:green">docker-compose up -d --build</strong>
- using <strong style="color:green">FireFox</strong> as a scraping browser

