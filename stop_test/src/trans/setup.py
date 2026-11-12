from setuptools import find_packages, setup


package_name = 'trans'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dev',
    maintainer_email='dev@example.com',
    description=(
        "Subscribes to manual_control's cmd topic and prints "
        '[steering, speed] to the terminal.'
    ),
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'trans = trans.trans_node:main',        ],
    },
)
