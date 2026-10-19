import rclpy
from rclpy.node import Node

from custom_interfaces.msg import RoombaState
from custom_interfaces.srv import SetPowerMode, ToggleCleaning


class VirtualRoomba(Node):
    def __init__(self):
        super().__init__('virtual_roomba')

        self.declare_parameter('drain_rate', 1.0)
        self.base_drain_rate = float(self.get_parameter('drain_rate').value)
        self.drain_rate = self.base_drain_rate

        self.battery_level = 100.0
        self.current_status = 'IDLE'
        self.power_mode = 'NORMAL'

        self.publisher_ = self.create_publisher(
            RoombaState, 'roomba_telemetry', 10
        )
        self.set_power_mode_service = self.create_service(
            SetPowerMode, 'set_power_mode', self.set_power_mode
        )
        self.toggle_cleaning_service = self.create_service(
            ToggleCleaning, 'toggle_cleaning', self.toggle_cleaning
        )
        self.timer = self.create_timer(1.0, self.timer_callback)

    def timer_callback(self):
        if self.current_status == 'CLEANING':
            self.battery_level = max(0.0, self.battery_level - self.drain_rate)
            if self.battery_level == 0.0:
                self.current_status = 'DEAD'
                self.get_logger().info('Battery depleted; cleaning stopped.')

        msg = RoombaState()
        msg.battery_level = self.battery_level
        msg.current_status = self.current_status
        msg.power_mode = self.power_mode
        self.publisher_.publish(msg)

    def set_power_mode(self, request, response):
        requested_mode = request.power_mode
        if requested_mode == self.power_mode:
            response.success = True
            response.message = f'Power mode is already {self.power_mode}.'
            return response

        mode_rates = {
            'NORMAL': self.base_drain_rate,
            'ECO': self.base_drain_rate * 0.5,
            'TURBO': self.base_drain_rate * 2.0,
        }
        if requested_mode not in mode_rates:
            response.success = False
            response.message = f'Unknown power mode: {requested_mode}.'
            self.get_logger().warning(response.message)
            return response

        self.power_mode = requested_mode
        self.drain_rate = mode_rates[requested_mode]
        response.success = True
        response.message = (
            f'Power mode set to {self.power_mode}; '
            f'drain rate is {self.drain_rate}.'
        )
        self.get_logger().info(response.message)
        return response

    def toggle_cleaning(self, request, response):
        if self.current_status == 'DEAD':
            response.success = False
            response.message = 'Cannot change cleaning state: the robot is DEAD.'
            self.get_logger().warning(response.message)
            return response

        if request.start_cleaning:
            if self.current_status == 'IDLE':
                self.current_status = 'CLEANING'
                response.message = 'Cleaning started.'
            else:
                response.message = 'Cleaning is already in progress.'
        elif self.current_status == 'CLEANING':
            self.current_status = 'IDLE'
            response.message = 'Cleaning stopped.'
        else:
            response.message = 'Cleaning is already stopped.'

        response.success = True
        self.get_logger().info(response.message)
        return response


def main(args=None):
    rclpy.init(args=args)
    node = VirtualRoomba()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
