from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='demo_nodes_cpp', executable='talker',   output='screen'),
        Node(package='demo_nodes_cpp', executable='listener', output='screen'),
        Node(package='demo_nodes_py',  executable='talker',   output='screen'),
        Node(package='demo_nodes_py',  executable='listener', output='screen'),
    ])
