from setuptools import setup, find_packages

setup(
    name="agent-browser",
    version="2.0.0",
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    install_requires=[
        "pyyaml>=6.0",
        "click>=8.0",
        "fastapi",
        "uvicorn[standard]",
        "websockets>=12.0",
        "httpx>=0.27.0",
        "langchain-anthropic",
        "langchain-openai",
        "browser-use==0.12.2",
    ],
    entry_points={
        'console_scripts': [
            'agent-browser=cli.commands:cli',
        ],
    },
)
