FROM ros:humble

# Install demo packages (lightweight nodes always present in ros:humble)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-demo-nodes-cpp \
    ros-humble-demo-nodes-py \
    python3-pip \
    python3-colcon-common-extensions \
 && rm -rf /var/lib/apt/lists/*

# Install dendROS (build context is the repo root)
COPY dendROS/ /usr/local/dendROS/
RUN pip3 install --no-cache-dir pyyaml \
 && chmod +x /usr/local/dendROS/dendROS_pipe.py \
 && printf '\n# dendROS — colorized ROS 2 output\nsource /usr/local/dendROS/dendROS.sh\n' \
    >> /root/.bashrc

# Build the test bringup package
COPY test/test_bringup/ /ros2_ws/src/test_bringup/
RUN bash -c "source /opt/ros/humble/setup.bash \
 && cd /ros2_ws \
 && colcon build --packages-select test_bringup --cmake-args -DCMAKE_BUILD_TYPE=Release" \
 && printf '\nsource /ros2_ws/install/setup.bash\n' >> /root/.bashrc

WORKDIR /ros2_ws
