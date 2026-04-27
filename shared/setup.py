from setuptools import setup, find_packages

setup(
    name="shared",
    version="0.1.0",
    description="Shared utilities for AscenAI microservices",
    packages=["shared"],
    package_dir={"shared": "."},
    install_requires=[
        "python-jose[cryptography]>=3.3.0",
        "presidio-analyzer>=2.2.351",
        "presidio-anonymizer>=2.2.351",
        "structlog>=24.1.0",
        "pydantic>=2.7.0"
    ],
)
