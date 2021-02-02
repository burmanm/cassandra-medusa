# -*- coding: utf-8 -*-
# Copyright 2019 Spotify AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import base64
import sys
import requests
import configparser
import logging
import os
import io
import itertools
import subprocess
from subprocess import PIPE
from dateutil import parser
from pathlib import Path

from libcloud.storage.providers import get_driver

from medusa.storage.s3_compat import S3BaseStorage

import medusa

class S3Storage(S3BaseStorage):
    """
    Available storage providers for S3:
    S3_AP_NORTHEAST = 's3_ap_northeast'
    S3_AP_NORTHEAST1 = 's3_ap_northeast_1'
    S3_AP_NORTHEAST2 = 's3_ap_northeast_2'
    S3_AP_SOUTH = 's3_ap_south'
    S3_AP_SOUTHEAST = 's3_ap_southeast'
    S3_AP_SOUTHEAST2 = 's3_ap_southeast2'
    S3_CA_CENTRAL = 's3_ca_central'
    S3_CN_NORTH = 's3_cn_north'
    S3_CN_NORTHWEST = 's3_cn_northwest'
    S3_EU_WEST = 's3_eu_west'
    S3_EU_WEST2 = 's3_eu_west_2'
    S3_EU_CENTRAL = 's3_eu_central'
    S3_SA_EAST = 's3_sa_east'
    S3_US_EAST2 = 's3_us_east_2'
    S3_US_WEST = 's3_us_west'
    S3_US_WEST_OREGON = 's3_us_west_oregon'
    S3_US_GOV_WEST = 's3_us_gov_west'
    S3_RGW = 's3_rgw'
    S3_RGW_OUTSCALE = 's3_rgw_outscale'
    """
    def get_aws_instance_profile(self):
        """
        Get IAM Role from EC2
        """
        logging.debug('Getting IAM Role:')
        try:
            aws_instance_profile = requests.get('http://169.254.169.254/latest/meta-data/iam/security-credentials',
                                                timeout=10)
        except requests.exceptions.RequestException:
            logging.warn('Can\'t fetch IAM Role.')
            return None

        if aws_instance_profile.status_code != 200:
            logging.debug("IAM Role not found.")
            return None
        else:
            return aws_instance_profile

    def connect_storage(self):
        """
        Connects to AWS S3 storage using EC2 driver

        :return driver: EC2 driver object
        """
        aws_security_token = ''
        aws_access_key_id = None
        # or authentication via AWS credentials file
        if self.config.key_file and os.path.exists(os.path.expanduser(self.config.key_file)):
            logging.debug("Reading AWS credentials from {}".format(
                self.config.key_file
            ))

            aws_config = configparser.ConfigParser(interpolation=None)
            with io.open(os.path.expanduser(self.config.key_file), 'r', encoding='utf-8') as aws_file:
                aws_config.read_file(aws_file)
                aws_profile = self.config.api_profile
                profile = aws_config[aws_profile]
                aws_access_key_id = profile['aws_access_key_id']
                aws_secret_access_key = profile['aws_secret_access_key']
        # Authentication via environment variables
        elif 'AWS_ACCESS_KEY_ID' in os.environ and \
                'AWS_SECRET_ACCESS_KEY' in os.environ:
            logging.debug("Reading AWS credentials from Environment Variables:")
            aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
            aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']

            # Access token for credentials fetched from STS service:
            if 'AWS_SECURITY_TOKEN' in os.environ:
                aws_security_token = os.environ['AWS_SECURITY_TOKEN']

        # or authentication via IAM Role credentials
        else:
            aws_instance_profile = self.get_aws_instance_profile()
            if aws_instance_profile:
                logging.debug('Reading AWS credentials from IAM Role: %s', aws_instance_profile.text)
                url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/" + aws_instance_profile.text
                try:
                    auth_data = requests.get(url).json()
                except requests.exceptions.RequestException:
                    logging.error('Can\'t fetch AWS IAM Role credentials.')
                    sys.exit(1)

                aws_access_key_id = auth_data['AccessKeyId']
                aws_secret_access_key = auth_data['SecretAccessKey']
                aws_security_token = auth_data['Token']

        if aws_access_key_id is None:
            raise NotImplementedError("No valid method of AWS authentication provided.")

        cls = get_driver(self.config.storage_provider)
        driver = cls(
            aws_access_key_id, aws_secret_access_key, token=aws_security_token, region=self.config.region
        )

        if self.config.transfer_max_bandwidth is not None:
            self.set_upload_bandwidth()

        return driver
