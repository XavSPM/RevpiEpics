
from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

setup(
    long_description=long_description,
    long_description_content_type='text/markdown',
    name='revpiepics',
    version='0.1.0',
    description='EPICS interface for Revolution Pi IOs',
    author='Xavier Goiziou',
    packages=find_packages(),
    install_requires=[
        'softioc>=4.6.1',
        'revpimodio2>=2.8.1',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: MIT License',
    ],
    python_requires='>=3.10',
)
