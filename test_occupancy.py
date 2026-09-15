from esp32_cameras import fetch_zone_frame
from slot_occupancy import check_slot_occupancy

fetch_zone_frame('zone-c', 'static/test_frame.jpg')
check_slot_occupancy('zone-c', 7, 'static/test_frame.jpg')
check_slot_occupancy('zone-c', 8, 'static/test_frame.jpg')
