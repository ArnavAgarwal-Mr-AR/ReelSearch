import re

title = '''Himani Chowdhary | Finance on Instagram: "🚨BIG UPDATE | New Rules

From October 1, several new changes have come into effect that will impact your electronics purchases, FD rates, EMIs, loans, insurance, investments and UPI transactions.

Checkout all the changes in the video
Share these new rules with everyone

(1 october 2026 new rules new changes financial rules upi electronics appliances prices have increased copper aluminium steel prices insurance irdai new guidelines emi fd interest rates)"'''

desc = '''67K likes, 487 comments - thehimanichaudhary on October 1, 2026: "🚨BIG UPDATE | New Rules

From October 1, several new changes have come into effect that will impact your electronics purchases, FD rates, EMIs, loans, insurance, investments and UPI transactions.

Checkout all the changes in the video
Share these new rules with everyone

(1 october 2026 new rules new changes financial rules upi electronics appliances prices have increased copper aluminium steel prices insurance irdai new guidelines emi fd interest rates)".'''

# Parse author and caption from desc
m_desc = re.search(r'-\s*([a-zA-Z0-9._]+)\s+on\s+[^:]+:\s*["\'\u201c](.*?)["\'\u201d]?\.?\s*$', desc, re.DOTALL)
if m_desc:
    print('Author handle:', m_desc.group(1))
    print('Caption preview:', m_desc.group(2)[:100])

# Parse creator name and title from title
m_title = re.search(r'^(.*?)\s+on\s+Instagram:\s*["\'\u201c]?(.*?)["\'\u201d]?$', title, re.DOTALL)
if m_title:
    print('Creator display name:', m_title.group(1))
    print('Title preview:', m_title.group(2)[:100])
