from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from popup_clicks import ButtonPackets


class ButtonTests(unittest.TestCase):
    def test_only_button_edges_emit_and_packets_can_be_fragmented(self):
        packets=ButtonPackets()
        self.assertEqual(packets.feed(bytes([8,30,20])),0)
        self.assertEqual(packets.feed(bytes([9])),0)
        self.assertEqual(packets.feed(bytes([0,0])),1)
        self.assertEqual(packets.feed(bytes([9,40,30,8,0,0])),0)
        self.assertEqual(packets.feed(bytes([10,0,0,11,0,0])),2)


if __name__=='__main__':unittest.main()
