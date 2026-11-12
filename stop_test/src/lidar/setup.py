from setuptools import find_packages, setup


package_name = 'lidar'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/lidar.launch.py']),
        ('share/' + package_name + '/config', ['config/fastdds_shm_profile.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dev',
    maintainer_email='dev@example.com',
    description='Ouster OS1 라이다 드라이버(ouster_ros)를 이 프로젝트 설정대로 실행하는 launch 레이어',
    license='Apache-2.0',
)
