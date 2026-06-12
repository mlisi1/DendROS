from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'test_bringup'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
            (os.path.join('share', 'test_bringup', 'config'), ['config/dendROS.yaml']),
],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dendros',
    maintainer_email='test@dendros.dev',
    description='Minimal bringup package for testing dendROS colorization',
    license='MIT',
    entry_points={'console_scripts': []},
)
