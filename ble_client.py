import asyncio
import threading
import uuid
import os
import datetime
import sys
import socket

BLE_AVAILABLE = False

try:
    import winrt.windows.devices.bluetooth as bluetooth
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt
    import winrt.windows.devices.bluetooth.advertisement as adv
    import winrt.windows.storage.streams as streams
    from winrt.windows.foundation import Deferral
    BLE_AVAILABLE = True
except ImportError as e:
    BLE_AVAILABLE = False
    _import_error = str(e)
else:
    _import_error = None


def _get_log_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(_get_log_dir(), 'ble_log.txt')


def _log(msg):
    line = f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}'
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _get_device_name():
    try:
        return socket.gethostname()
    except Exception:
        return 'TPad'


SERVICE_UUID = uuid.UUID("0000ffe0-0000-1000-8000-00805f9b34fb")
WRITE_CHAR_UUID = uuid.UUID("0000ffe1-0000-1000-8000-00805f9b34fb")
NOTIFY_CHAR_UUID = uuid.UUID("0000ffe2-0000-1000-8000-00805f9b34fb")
DEVICE_NAME = _get_device_name()


class BLEPeripheral:
    def __init__(self):
        self.service_provider = None
        self.local_service = None
        self.write_characteristic = None
        self.notify_characteristic = None
        self.connected = False
        self.advertising = False
        self.loop = None
        self._thread = None
        self._running = False
        self.on_data_received = None
        self.on_connection_change = None

    def start(self):
        if not BLE_AVAILABLE:
            _log(f'[BLE] 蓝牙不可用: {_import_error}')
            return False
        if self._running:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            _log(f'[BLE] 服务端错误: {e}')
            import traceback
            _log(f'[BLE] {traceback.format_exc()}')
        finally:
            try:
                self.loop.run_until_complete(self._cleanup())
            except Exception:
                pass
            self.loop.close()
            self.loop = None
            self.advertising = False
            self.connected = False
            if self.on_connection_change:
                self.on_connection_change(False)

    async def _main(self):
        _log('[BLE] 初始化 GATT 服务...')
        
        service_result = await gatt.GattServiceProvider.create_async(SERVICE_UUID)
        
        if service_result.service_provider is None:
            error_val = getattr(service_result.error, 'value', 'unknown')
            _log(f'[BLE] 创建 GATT 服务失败，错误码: {error_val}')
            await asyncio.sleep(1)
            return

        self.service_provider = service_result.service_provider
        self.local_service = self.service_provider.service
        _log('[BLE] GATT 服务创建成功')

        write_params = gatt.GattLocalCharacteristicParameters()
        write_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE | 
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
        )
        write_params.read_protection_level = gatt.GattProtectionLevel.PLAIN
        write_params.write_protection_level = gatt.GattProtectionLevel.PLAIN
        
        write_result = await self.local_service.create_characteristic_async(
            WRITE_CHAR_UUID, write_params
        )
        if write_result.characteristic is None:
            _log(f'[BLE] 创建写入特征值失败，错误码: {write_result.error}')
            return
        self.write_characteristic = write_result.characteristic
        _log('[BLE] 写入特征值创建成功')

        notify_params = gatt.GattLocalCharacteristicParameters()
        notify_params.characteristic_properties = gatt.GattCharacteristicProperties.NOTIFY
        notify_params.read_protection_level = gatt.GattProtectionLevel.PLAIN
        notify_params.write_protection_level = gatt.GattProtectionLevel.PLAIN
        
        notify_result = await self.local_service.create_characteristic_async(
            NOTIFY_CHAR_UUID, notify_params
        )
        if notify_result.characteristic is None:
            _log(f'[BLE] 创建通知特征值失败，错误码: {notify_result.error}')
            return
        self.notify_characteristic = notify_result.characteristic
        _log('[BLE] 通知特征值创建成功')

        self.service_provider.add_advertisement_status_changed(
            self._on_advertisement_status_changed
        )
        _log('[BLE] 广告状态事件注册成功')

        self.write_characteristic.add_write_requested(
            self._on_write_requested
        )
        _log('[BLE] 写入请求事件注册成功')

        self.notify_characteristic.add_subscribed_clients_changed(
            self._on_subscribed_clients_changed
        )
        _log('[BLE] 订阅客户端变化事件注册成功')

        _log('[BLE] 开始广播...')
        try:
            adv_params = gatt.GattServiceProviderAdvertisingParameters()
            adv_params.is_discoverable = True
            adv_params.is_connectable = True
            result = self.service_provider.start_advertising_with_parameters(adv_params)
            _log(f'[BLE] start_advertising_with_parameters 返回值: {result}')
        except Exception as e:
            _log(f'[BLE] start_advertising_with_parameters 异常: {e}')
            try:
                result = self.service_provider.start_advertising()
                _log(f'[BLE] start_advertising 返回值: {result}')
            except Exception as e2:
                _log(f'[BLE] start_advertising 也异常: {e2}')
        _log(f'[BLE] 广播启动调用完成，等待状态变更...')
        
        await asyncio.sleep(1)
        status = getattr(self.service_provider, 'advertisement_status', None)
        _log(f'[BLE] 当前广播状态值: {status}')
        if status == 2:
            self.advertising = True
            _log('[BLE] 广播已成功启动 (直接检测)')

        while self._running:
            await asyncio.sleep(1)

    def _on_advertisement_status_changed(self, sender, args):
        status = args.status
        _log(f'[BLE] 广播状态变化: {status}')
        if status == 2:
            self.advertising = True
            _log('[BLE] 广播已成功启动')
        elif status == 0:
            self.advertising = False
            _log('[BLE] 广播已停止')

    def _on_subscribed_clients_changed(self, sender, args):
        clients = list(sender.subscribed_clients)
        count = len(clients)
        _log(f'[BLE] 订阅客户端变化: {count} 个')
        if count > 0 and not self.connected:
            self.connected = True
            self.advertising = False
            _log('[BLE] 客户端已连接')
            if self.on_connection_change:
                self.on_connection_change(True)
        elif count == 0 and self.connected:
            self.connected = False
            _log('[BLE] 客户端已断开')
            if self.on_connection_change:
                self.on_connection_change(False)
            self.stop()

    def _on_write_requested(self, sender, args):
        try:
            deferral = args.get_deferral()
            request = None

            async def get_request():
                nonlocal request
                request = await args.get_request_async()

            asyncio.new_event_loop().run_until_complete(get_request())
            
            reader = streams.DataReader.from_buffer(request.value)
            n_bytes = reader.unconsumed_buffer_length
            data = bytearray(n_bytes)
            reader.read_bytes(data)
            text = data.decode('utf-8', errors='ignore')
            _log(f'[BLE] 收到数据: {text}')
            
            if self.on_data_received:
                self.on_data_received(text, bytes(data))
            
            if request.option == gatt.GattWriteOption.WRITE_WITH_RESPONSE:
                request.respond()
            
            deferral.complete()
        except Exception as e:
            _log(f'[BLE] 数据处理失败: {e}')
            import traceback
            _log(f'[BLE] {traceback.format_exc()}')

    async def _cleanup(self):
        if self.service_provider:
            try:
                self.service_provider.stop_advertising()
            except Exception as e:
                _log(f'[BLE] 停止广播失败: {e}')
        self.service_provider = None
        self.local_service = None
        self.write_characteristic = None
        self.notify_characteristic = None
        self.advertising = False
        self.connected = False
        self._running = False
        _log('[BLE] 服务已停止')

    def send_data(self, text):
        if not self.connected or not self.notify_characteristic:
            return False
        data = text.encode('utf-8')
        try:
            asyncio.run_coroutine_threadsafe(
                self._notify_value(data),
                self.loop
            )
            return True
        except Exception as e:
            _log(f'[BLE] 发送失败: {e}')
            return False

    async def _notify_value(self, data):
        try:
            writer = streams.DataWriter()
            writer.write_bytes(data)
            await self.notify_characteristic.notify_value_async(writer.detach_buffer())
        except Exception as e:
            _log(f'[BLE] 通知失败: {e}')

    def is_advertising(self):
        return self.advertising

    def is_connected(self):
        return self.connected


_ble_peripheral = None


def get_ble_peripheral():
    global _ble_peripheral
    if _ble_peripheral is None:
        _ble_peripheral = BLEPeripheral()
    return _ble_peripheral
