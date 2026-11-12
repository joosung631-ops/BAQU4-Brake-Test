from glob import glob
from setuptools import find_packages, setup

setup(
    name="lidar_cone", version="0.2.0", packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/lidar_cone"]),
        ("share/lidar_cone", ["package.xml", "README.md"]),
        ("share/lidar_cone/config", glob("config/*")),
        ("share/lidar_cone/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "numpy", "PyYAML"],
    tests_require=["pytest"],
    zip_safe=True,
    maintainer="celos4", maintainer_email="celos4@example.com",
    description="Ouster cone detection with explicit coordinate calibration",
    license="MIT",
    entry_points={"console_scripts": [
        "cone_detector = lidar_cone.node:main",
        "cone_bag_review = lidar_cone.offline:main",
    ]},
)
