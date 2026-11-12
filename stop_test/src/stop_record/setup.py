from setuptools import find_packages, setup


package_name = 'stop_record'

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
    description='stop_test 컨테이너 전용: 제동 시험 토픽을 검증하고 ros2 bag record를 실행합니다.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'record = stop_record.record_node:main',
        ],
    },
)
