import serial


PORT = "COM37"
BAUD_RATE = 115200


COMMANDS = {
    "1": "IDLE",
    "2": "THINKING",
    "3": "WRITING",
    "4": "RUNNING",
    "5": "DONE",
    "6": "ERROR",
    "7": "TOKEN:75",
}


def show_menu():
    print()
    print("ESP32-S3 AI Agent 状态灯控制")
    print("1 IDLE")
    print("2 THINKING")
    print("3 WRITING")
    print("4 RUNNING")
    print("5 DONE")
    print("6 ERROR")
    print("7 TOKEN:75")
    print("q 退出")


def send_command(ser, command):
    ser.write((command + "\n").encode("utf-8"))
    print(f"已发送：{command}")


def main():
    try:
        ser = serial.Serial(PORT, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"无法打开串口 {PORT}：{e}")
        return

    print(f"已连接 {PORT}，波特率 {BAUD_RATE}")

    try:
        while True:
            show_menu()
            choice = input("请输入选项：").strip().lower()

            if choice == "q":
                print("退出程序")
                break

            if choice in COMMANDS:
                send_command(ser, COMMANDS[choice])
            else:
                print("无效选项，请重新输入")
    finally:
        ser.close()
        print("串口已关闭")


if __name__ == "__main__":
    main()
