# -*- coding: utf-8 -*-
import unittest
import sys
import os

# Ensure src module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.storage import DatabaseManager

class TestStorage(unittest.TestCase):
    
    def test_parse_sniper_value(self):
        """测试解析狙击点位数值"""
        
        # 1. 正常数值
        self.assertEqual(DatabaseManager._parse_sniper_value(100), 100.0)
        self.assertEqual(DatabaseManager._parse_sniper_value(100.5), 100.5)
        self.assertEqual(DatabaseManager._parse_sniper_value("100"), 100.0)
        self.assertEqual(DatabaseManager._parse_sniper_value("100.5"), 100.5)
        
        # 2. 包含中文描述和"元"
        self.assertEqual(DatabaseManager._parse_sniper_value("建议在 100 元附近买入"), 100.0)
        self.assertEqual(DatabaseManager._parse_sniper_value("价格：100.5元"), 100.5)
        
        # 3. 包含干扰数字（修复的Bug场景）
        # 之前 "MA5" 会被错误提取为 5.0，现在应该提取 "元" 前面的 100
        text_bug = "无法给出。需等待MA5数据恢复，在股价回踩MA5且乖离率<2%时考虑100元"
        self.assertEqual(DatabaseManager._parse_sniper_value(text_bug), 100.0)
        
        # 4. 更多干扰场景
        text_complex = "MA10为20.5，建议在30元买入"
        self.assertEqual(DatabaseManager._parse_sniper_value(text_complex), 30.0)
        
        text_multiple = "支撑位10元，阻力位20元" # 应该提取最后一个"元"前面的数字，即20，或者更复杂的逻辑？
        # 当前逻辑是找最后一个冒号，然后找之后的第一个"元"，提取中间的数字。
        # 测试没有冒号的情况
        self.assertEqual(DatabaseManager._parse_sniper_value("30元"), 30.0)
        
        # 测试多个数字在"元"之前
        self.assertEqual(DatabaseManager._parse_sniper_value("MA5 10 20元"), 20.0)
        
        # 5. Fallback: no "元" character — extracts last non-MA number
        self.assertEqual(DatabaseManager._parse_sniper_value("102.10-103.00（MA5附近）"), 103.0)
        self.assertEqual(DatabaseManager._parse_sniper_value("97.62-98.50（MA10附近）"), 98.5)
        self.assertEqual(DatabaseManager._parse_sniper_value("93.40下方（MA20支撑）"), 93.4)
        self.assertEqual(DatabaseManager._parse_sniper_value("108.00-110.00（前期高点阻力）"), 110.0)

        # 6. 无效输入
        self.assertIsNone(DatabaseManager._parse_sniper_value(None))
        self.assertIsNone(DatabaseManager._parse_sniper_value(""))
        self.assertIsNone(DatabaseManager._parse_sniper_value("没有数字"))
        self.assertIsNone(DatabaseManager._parse_sniper_value("MA5但没有元"))

if __name__ == '__main__':
    unittest.main()
