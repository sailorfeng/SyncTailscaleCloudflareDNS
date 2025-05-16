from setuptools import setup, find_packages

setup(
    name="tailscale-cloudflare-sync",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "requests",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "ts-cf-sync=sync:main",
        ],
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="Syncs Tailscale devices to Cloudflare DNS.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/tailscale-cloudflare-sync", # Replace with your repo URL
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
