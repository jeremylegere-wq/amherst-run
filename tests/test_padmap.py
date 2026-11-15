import unittest

from game import padmap

CFG = ("060000005e040000120b000011050000,Microsoft Xbox Controller,platform:Linux,b:b2,a:b1,dpdown:h0.4,leftx:a0,"
       "start:b8,back:b7,x:b3,y:b4,leftshoulder:b5,rightshoulder:b6,guide:b9,\n"
       "06000000d62000006320000005010000,Microsoft Xbox Controller,platform:Linux,b:b2,a:b1,start:b8,back:b7,x:b3,y:b4,")


class PadMap(unittest.TestCase):
    def test_batocera_numbers_from_one(self):
        m = padmap.parse(CFG, "06000000D62000006320000005010000")
        self.assertEqual((m["a"], m["b"], m["start"], m["back"], m["x"]), (1, 2, 8, 7, 3))

    def test_literal_backslash_n_separator(self):
        m = padmap.parse(CFG.replace("\n", "\\n"), "060000005e040000120b000011050000")
        self.assertEqual(m["a"], 1)

    def test_unknown_pad_gets_none(self):
        self.assertIsNone(padmap.parse(CFG, "ffff"))
        self.assertIsNone(padmap.parse("", "x"))

    def test_menu_a_chooses_on_offset_layout(self):
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        from game.menu import Menu
        padmap.BTN.update(padmap.parse(CFG, "060000005e040000120b000011050000"))
        try:
            m = Menu.__new__(Menu)
            m.index = 0
            r = m.handle_event(pygame.event.Event(pygame.JOYBUTTONDOWN, button=1))
            self.assertEqual(r, ("choose", "1p"))          # raw button 1 is A here, it used to quit the game
        finally:
            padmap.BTN.update(padmap.STANDARD)


if __name__ == "__main__":
    unittest.main()
