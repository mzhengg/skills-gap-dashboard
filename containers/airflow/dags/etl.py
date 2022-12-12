import random
import string

from tempfile import mkdtemp

from selenium import webdriver
from selenium.webdriver.common.by import By

from airflow import DAG
from airflow.operators.python import PythonOperator

import boto3

# have to set a bunch of options for headless chrome driver to work on lambda
options = webdriver.ChromeOptions()
options.binary_location = '/opt/chrome/chrome'
options.add_argument('--user-agent="Mozilla/5.0 (Windows Phone 10.0; Android 4.2.1; Microsoft; Lumia 640 XL LTE) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.135 Mobile Safari/537.36 Edge/12.10166"')
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1280x1696")
options.add_argument("--single-process")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-dev-tools")
options.add_argument("--no-zygote")
options.add_argument(f"--user-data-dir={mkdtemp()}")
options.add_argument(f"--data-path={mkdtemp()}")
options.add_argument(f"--disk-cache-dir={mkdtemp()}")
options.add_argument("--remote-debugging-port=9222")

# get from terraform directory: "mzheng-${var.aws_s3_bucket}"
bucket_name = 'mzheng-indeed-job-posts'

# list of jobs to be scraped (allow more job types later?)
jobs = [['Software Engineer', '', '20']]

def get_page_links(job, location, no_of_pages):
    # modify url to include job
    job = job.replace(' ', '%20')
    url = f'https://www.indeed.com/jobs?q={job}'

    # modify url to include job and location
    location = location.replace(' ', '%20')
    url = url + f'&l={location}'

    # links for each page to be scraped
    page_links = []

    for page in range(no_of_pages):
        page_links.append(url + f'&start={page*10}')

    return page_links

def get_job_links(page_links):
    # initializes chrome driver
    driver = webdriver.Chrome("/opt/chromedriver", options=options)
    
    # list of all href links from all the pages
    links = []
    
    # list of all job links from all the pages 
    job_links = []
    
    # cycle through each page of indeed
    for link in page_links:
        # opens the link 
        driver.get(link)

        # list of all elements on the page with <a>
        elements = driver.find_elements(By.TAG_NAME, 'a')
    
        # finds the href link in each <a> element
        for element in elements:
            link = element.get_attribute('href')
            links.append(link)
      
      # filter the links by job links
        for link in links:
            if link is None:
                continue
        
            if 'clk?' in link:
                job_links.append(link)

    # make sure that job links are being scraped
    if len(job_links) == 0:
        print("No links were scraped")

    return job_links

def scraper(job_link):
    # initializes chrome driver
    driver = webdriver.Chrome("/opt/chromedriver", options=options)

    # opens the url
    driver.get(job_link)
    
    # return all the text on the page
    job_info = driver.find_element(By.TAG_NAME, 'body').text

    return job_info

def upload_to_s3(job_links, bucket_name, directory):
    # scrape information from each job post
    for link in job_links:
        # file to be uploaded
        scraped_posting = scraper(link)

        # file name for scraped posting
        file_name = ''.join(random.choices(string.ascii_letters, k=10))

        # client to bundle configuration needed for API requests
        client = boto3.client('s3')

        # uploads file to s3 bucket
        response = client.put_object(Bucket=bucket_name, Body=scraped_posting, Key=f'{directory}/{file_name}.txt')

def indeed_scraper(jobs):
    # scrape postings for each 'job'
    for job in jobs:
        page_links = get_page_links(job[0], job[1], job[2])
        job_links = get_job_links(page_links)
        upload_to_s3(job_links, bucket_name, job[0])

### Airflow ###

default_args = {
    'owner': 'airflow',
    'start_date': '2022-1-1',
    'depends_on_past': False, # keeps DAG from being triggered if previous schedule for task unsuccessful
    'retries': 1, # number of retries before failing a task
}

with DAG(
    dag_id = 'scraper_dag',
    schedule_interval = '@weekly',
    default_args = default_args,
    catchup = True, # run any past scheduled tasks that have not been run to catch up
    max_active_runs = 1, # max number of concurrent instances of a DAG there are allowed to be
    tags = ['scraper_dag']

) as dag:
    run_indeed_scraper = PythonOperator(
        task_id = 'run_indeed_scraper',
        python_callable = indeed_scraper, # name of function
        op_kwargs = { # function parameters
            'jobs': jobs
        }
    )