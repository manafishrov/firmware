import configparser
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_config():
    '''Load and return configuration from config.ini'''
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), '../config.ini')
    if not os.path.exists(config_path):
        logging.error('Config file not found')
        raise FileNotFoundError('config.ini not found')
    config.read(config_path)
    return config

def get_ip_address():
    return load_config()['network']['ip_address']

def get_motor_port():
    return load_config()['network']['motor_control_port']
