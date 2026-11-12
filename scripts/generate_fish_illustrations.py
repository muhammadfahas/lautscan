"""Generate 13 uniform, high-quality SVG illustrations for marine species in LautScan."""
import os

SPECIES_DATA = {
    "thunnus_albacares": {
        "title": "Tuna Sirip Kuning",
        "scientific": "Thunnus albacares",
        "family": "Scombridae · Pelagis Besar",
        "glow": "#F59E0B",
        "svg_content": """
            <!-- Body Gradient -->
            <defs>
                <linearGradient id="tunaback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#0E2338" />
                    <stop offset="40%" stop-color="#1E3A5F" />
                    <stop offset="70%" stop-color="#3B82F6" />
                    <stop offset="85%" stop-color="#94A3B8" />
                    <stop offset="100%" stop-color="#F1F5F9" />
                </linearGradient>
                <linearGradient id="yellowfin" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#F59E0B" />
                    <stop offset="100%" stop-color="#FBBF24" />
                </linearGradient>
            </defs>
            <!-- Caudal Fin (Tail) -->
            <path d="M 330 130 Q 365 75 385 60 Q 365 125 350 130 Q 365 135 385 200 Q 365 185 330 130 Z" fill="#F59E0B" opacity="0.95"/>
            <path d="M 335 130 Q 360 85 375 72 Q 355 125 345 130 Q 355 135 375 188 Q 360 175 335 130 Z" fill="#1E3A5F"/>
            <!-- Second Dorsal Fin (Long sickle yellow) -->
            <path d="M 235 98 Q 255 35 295 18 Q 275 65 258 103 Z" fill="url(#yellowfin)"/>
            <!-- Anal Fin (Long sickle yellow) -->
            <path d="M 240 162 Q 260 225 298 242 Q 280 195 262 157 Z" fill="url(#yellowfin)"/>
            <!-- First Dorsal Fin -->
            <path d="M 140 102 Q 185 60 225 98 Z" fill="#1E3A5F" stroke="#F59E0B" stroke-width="1.5"/>
            <!-- Finlets top and bottom -->
            <polygon points="268,107 278,98 276,108" fill="#F59E0B"/>
            <polygon points="282,112 292,104 290,113" fill="#F59E0B"/>
            <polygon points="296,117 305,110 303,118" fill="#F59E0B"/>
            <polygon points="310,122 318,116 317,123" fill="#F59E0B"/>
            <polygon points="270,153 280,162 278,152" fill="#F59E0B"/>
            <polygon points="284,148 294,156 292,147" fill="#F59E0B"/>
            <polygon points="298,143 307,150 305,142" fill="#F59E0B"/>
            <polygon points="312,138 320,144 319,137" fill="#F59E0B"/>
            <!-- Main Torpedo Body -->
            <path d="M 40 130 Q 75 90 150 90 Q 250 90 335 130 Q 250 170 150 170 Q 75 170 40 130 Z" fill="url(#tunaback)"/>
            <!-- Belly Iridescence & Silver Glow -->
            <path d="M 65 130 Q 120 120 200 120 Q 280 125 330 130 Q 250 168 150 168 Q 90 168 65 130 Z" fill="#FFFFFF" opacity="0.35"/>
            <!-- Pectoral Fin -->
            <path d="M 125 128 Q 185 132 230 148 Q 175 142 125 136 Z" fill="#0F172A" stroke="#F59E0B" stroke-width="1"/>
            <!-- Gill Cover -->
            <path d="M 110 102 Q 125 130 110 158" fill="none" stroke="#F59E0B" stroke-width="1.8" opacity="0.6"/>
            <!-- Eye -->
            <circle cx="78" cy="118" r="7" fill="#FBBF24"/>
            <circle cx="78" cy="118" r="4.5" fill="#0F172A"/>
            <circle cx="76" cy="116" r="1.5" fill="#FFFFFF"/>
            <!-- Mouth Line -->
            <path d="M 40 130 Q 60 132 70 134" fill="none" stroke="#0E2338" stroke-width="2"/>
        """
    },
    "thunnus_obesus": {
        "title": "Tuna Mata Besar (Bigeye)",
        "scientific": "Thunnus obesus",
        "family": "Scombridae · Pelagis Dalam",
        "glow": "#38BDF8",
        "svg_content": """
            <defs>
                <linearGradient id="bigeyeback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#08182B" />
                    <stop offset="35%" stop-color="#172554" />
                    <stop offset="65%" stop-color="#2563EB" />
                    <stop offset="85%" stop-color="#93C5FD" />
                    <stop offset="100%" stop-color="#F8FAFC" />
                </linearGradient>
            </defs>
            <path d="M 330 130 Q 365 72 385 58 Q 365 125 350 130 Q 365 135 385 202 Q 365 188 330 130 Z" fill="#F59E0B"/>
            <path d="M 335 130 Q 360 82 375 70 Q 355 125 345 130 Q 355 135 375 190 Q 360 178 335 130 Z" fill="#172554"/>
            <path d="M 230 96 Q 248 50 278 38 Q 262 75 250 102 Z" fill="#F59E0B"/>
            <path d="M 235 164 Q 252 210 280 222 Q 265 185 252 158 Z" fill="#F59E0B"/>
            <path d="M 135 98 Q 180 55 220 96 Z" fill="#1E3A8A" stroke="#38BDF8" stroke-width="1.5"/>
            <!-- Deeper Torpedo Body -->
            <path d="M 40 130 Q 75 82 145 82 Q 245 82 335 130 Q 245 178 145 178 Q 75 178 40 130 Z" fill="url(#bigeyeback)"/>
            <!-- Characteristic Large Eye with Golden Ring -->
            <circle cx="80" cy="116" r="11" fill="#FBBF24" stroke="#38BDF8" stroke-width="1.5"/>
            <circle cx="80" cy="116" r="7.5" fill="#020617"/>
            <circle cx="77" cy="113" r="2.5" fill="#FFFFFF"/>
            <!-- Long Pectoral Fin -->
            <path d="M 125 128 Q 190 134 245 146 Q 180 144 125 138 Z" fill="#091E3A" stroke="#38BDF8" stroke-width="1"/>
            <path d="M 112 96 Q 128 128 112 164" fill="none" stroke="#60A5FA" stroke-width="1.8" opacity="0.5"/>
            <path d="M 40 130 Q 62 133 72 135" fill="none" stroke="#08182B" stroke-width="2"/>
        """
    },
    "katsuwonus_pelamis": {
        "title": "Ikan Cakalang (Skipjack)",
        "scientific": "Katsuwonus pelamis",
        "family": "Scombridae · Pelagis Cepat",
        "glow": "#A855F7",
        "svg_content": """
            <defs>
                <linearGradient id="cakalangback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#1E1B4B" />
                    <stop offset="35%" stop-color="#312E81" />
                    <stop offset="60%" stop-color="#4F46E5" />
                    <stop offset="80%" stop-color="#E0E7FF" />
                    <stop offset="100%" stop-color="#FFFFFF" />
                </linearGradient>
            </defs>
            <path d="M 330 130 Q 365 80 385 65 Q 365 125 350 130 Q 365 135 385 195 Q 365 180 330 130 Z" fill="#312E81"/>
            <path d="M 235 104 Q 250 70 272 60 Q 258 88 250 108 Z" fill="#6366F1"/>
            <path d="M 240 156 Q 255 190 275 200 Q 260 172 252 152 Z" fill="#6366F1"/>
            <path d="M 140 105 Q 185 70 225 104 Z" fill="#312E81"/>
            <!-- Torpedo Body -->
            <path d="M 42 130 Q 75 92 145 92 Q 245 92 335 130 Q 245 168 145 168 Q 75 168 42 130 Z" fill="url(#cakalangback)"/>
            <!-- 5 Signature Longitudinal Dark Belly Stripes -->
            <path d="M 130 136 Q 200 134 265 134" fill="none" stroke="#312E81" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M 125 143 Q 195 142 270 141" fill="none" stroke="#312E81" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M 122 150 Q 195 150 268 148" fill="none" stroke="#312E81" stroke-width="2.5" stroke-linecap="round"/>
            <path d="M 125 157 Q 195 158 260 155" fill="none" stroke="#312E81" stroke-width="2" stroke-linecap="round"/>
            <!-- Eye & Gill -->
            <circle cx="78" cy="118" r="7.5" fill="#FDE047"/>
            <circle cx="78" cy="118" r="4.5" fill="#0F172A"/>
            <circle cx="76" cy="116" r="1.5" fill="#FFFFFF"/>
            <path d="M 112 104 Q 124 130 112 156" fill="none" stroke="#A5B4FC" stroke-width="1.8"/>
            <path d="M 124 128 Q 170 132 205 142 Q 165 138 124 134 Z" fill="#1E1B4B"/>
        """
    },
    "euthynnus_affinis": {
        "title": "Ikan Tongkol Komo",
        "scientific": "Euthynnus affinis",
        "family": "Scombridae · Pelagis Pesisir",
        "glow": "#06B6D4",
        "svg_content": """
            <defs>
                <linearGradient id="tongkolback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#083344" />
                    <stop offset="40%" stop-color="#0E7490" />
                    <stop offset="70%" stop-color="#22D3EE" />
                    <stop offset="85%" stop-color="#CFFAFE" />
                    <stop offset="100%" stop-color="#FFFFFF" />
                </linearGradient>
            </defs>
            <path d="M 330 130 Q 365 80 385 65 Q 365 125 350 130 Q 365 135 385 195 Q 365 180 330 130 Z" fill="#0E7490"/>
            <path d="M 140 102 Q 180 65 220 102 Z" fill="#083344"/>
            <path d="M 40 130 Q 75 92 145 92 Q 245 92 335 130 Q 245 168 145 168 Q 75 168 40 130 Z" fill="url(#tongkolback)"/>
            <!-- Broken Wavy Marks on Upper Back -->
            <path d="M 170 102 Q 185 112 195 104 Q 210 114 220 106 Q 235 116 248 108 Q 262 118 275 110" fill="none" stroke="#083344" stroke-width="2.5"/>
            <path d="M 185 114 Q 200 122 212 115 Q 225 124 238 116 Q 252 125 265 118" fill="none" stroke="#083344" stroke-width="2.2"/>
            <!-- Characteristic Dark Spots between Pectoral and Pelvic Fins -->
            <circle cx="148" cy="144" r="3.5" fill="#083344"/>
            <circle cx="158" cy="148" r="3" fill="#083344"/>
            <circle cx="168" cy="145" r="3.2" fill="#083344"/>
            <circle cx="178" cy="150" r="2.8" fill="#083344"/>
            <circle cx="78" cy="118" r="7" fill="#67E8F9"/>
            <circle cx="78" cy="118" r="4.5" fill="#083344"/>
            <circle cx="76" cy="116" r="1.5" fill="#FFFFFF"/>
            <path d="M 110 102 Q 124 130 110 158" fill="none" stroke="#083344" stroke-width="1.8"/>
            <path d="M 122 128 Q 170 132 205 140 Q 165 138 122 134 Z" fill="#083344"/>
        """
    },
    "rastrelliger_kanagurta": {
        "title": "Ikan Kembung Lelaki",
        "scientific": "Rastrelliger kanagurta",
        "family": "Scombridae · Pelagis Kecil",
        "glow": "#10B981",
        "svg_content": """
            <defs>
                <linearGradient id="kembungback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#064E3B" />
                    <stop offset="35%" stop-color="#059669" />
                    <stop offset="65%" stop-color="#34D399" />
                    <stop offset="85%" stop-color="#A7F3D0" />
                    <stop offset="100%" stop-color="#FFFFFF" />
                </linearGradient>
            </defs>
            <path d="M 330 130 Q 360 85 380 72 Q 360 125 348 130 Q 360 135 380 188 Q 360 175 330 130 Z" fill="#059669"/>
            <path d="M 135 102 Q 170 72 205 102 Z" fill="#047857"/>
            <path d="M 220 105 Q 240 85 260 105 Z" fill="#047857"/>
            <path d="M 45 130 Q 80 95 145 95 Q 245 95 330 130 Q 245 165 145 165 Q 80 165 45 130 Z" fill="url(#kembungback)"/>
            <!-- Dark Longitudinal Back Bands / Vermiculations -->
            <path d="M 115 108 Q 175 104 235 108 Q 285 114 315 120" fill="none" stroke="#064E3B" stroke-width="2" stroke-dasharray="6,3"/>
            <path d="M 125 116 Q 185 112 245 116 Q 285 122 315 126" fill="none" stroke="#064E3B" stroke-width="2" stroke-dasharray="8,4"/>
            <!-- Characteristic Black Spot near Pectoral Fin -->
            <circle cx="120" cy="124" r="3.5" fill="#064E3B"/>
            <circle cx="78" cy="120" r="7.5" fill="#FDE047"/>
            <circle cx="78" cy="120" r="4.5" fill="#064E3B"/>
            <circle cx="76" cy="118" r="1.5" fill="#FFFFFF"/>
            <path d="M 105 104 Q 118 130 105 156" fill="none" stroke="#064E3B" stroke-width="1.8"/>
            <path d="M 120 128 Q 165 132 195 138 Q 160 136 120 133 Z" fill="#047857"/>
        """
    },
    "decapterus_russelli": {
        "title": "Ikan Layang Deles",
        "scientific": "Decapterus russelli",
        "family": "Carangidae · Pelagis Kecil",
        "glow": "#38BDF8",
        "svg_content": """
            <defs>
                <linearGradient id="layangback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#0C4A6E" />
                    <stop offset="35%" stop-color="#0284C7" />
                    <stop offset="65%" stop-color="#38BDF8" />
                    <stop offset="85%" stop-color="#BAE6FD" />
                    <stop offset="100%" stop-color="#FFFFFF" />
                </linearGradient>
            </defs>
            <path d="M 335 130 Q 365 85 382 72 Q 362 125 350 130 Q 362 135 382 188 Q 365 175 335 130 Z" fill="#0284C7"/>
            <path d="M 130 105 Q 165 80 200 105 Z" fill="#0284C7"/>
            <path d="M 215 106 Q 255 90 285 108 Z" fill="#0284C7"/>
            <!-- Slender Fusiform Body -->
            <path d="M 40 130 Q 75 100 145 100 Q 245 100 335 130 Q 245 160 145 160 Q 75 160 40 130 Z" fill="url(#layangback)"/>
            <!-- Prominent Lateral Line with Scutes near Tail -->
            <path d="M 105 124 Q 185 124 235 130 L 325 130" fill="none" stroke="#FDE047" stroke-width="1.8"/>
            <!-- Scutes (durian sisik keras) near tail -->
            <path d="M 255 126 L 258 134 M 265 126 L 268 134 M 275 126 L 278 134 M 285 126 L 288 134 M 295 126 L 298 134 M 305 126 L 308 134 M 315 126 L 318 134" stroke="#0369A1" stroke-width="1.5"/>
            <!-- Opercular Black Spot -->
            <circle cx="110" cy="115" r="3.5" fill="#082F49"/>
            <circle cx="75" cy="120" r="7" fill="#BAE6FD"/>
            <circle cx="75" cy="120" r="4" fill="#082F49"/>
            <circle cx="73" cy="118" r="1.5" fill="#FFFFFF"/>
            <path d="M 102 108 Q 114 130 102 152" fill="none" stroke="#082F49" stroke-width="1.6"/>
            <path d="M 115 128 Q 155 132 185 138 Q 150 136 115 132 Z" fill="#0284C7"/>
        """
    },
    "scomberomorus_commerson": {
        "title": "Ikan Tenggiri",
        "scientific": "Scomberomorus commerson",
        "family": "Scombridae · Predator Pelagis",
        "glow": "#64748B",
        "svg_content": """
            <defs>
                <linearGradient id="tenggiriback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#1E293B" />
                    <stop offset="35%" stop-color="#334155" />
                    <stop offset="65%" stop-color="#64748B" />
                    <stop offset="85%" stop-color="#CBD5E1" />
                    <stop offset="100%" stop-color="#F8FAFC" />
                </linearGradient>
            </defs>
            <path d="M 345 130 Q 375 80 390 68 Q 372 125 360 130 Q 372 135 390 192 Q 375 180 345 130 Z" fill="#334155"/>
            <path d="M 130 108 Q 185 92 235 108 Z" fill="#1E293B"/>
            <path d="M 245 108 Q 260 85 278 108 Z" fill="#334155"/>
            <!-- Elongated Torpedo Body -->
            <path d="M 30 130 Q 70 104 150 104 Q 260 104 345 130 Q 260 156 150 156 Q 70 156 30 130 Z" fill="url(#tenggiriback)"/>
            <!-- Vertical Wavy Zebra Bars Across Body -->
            <path d="M 140 110 Q 142 130 138 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 155 110 Q 158 130 154 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 170 110 Q 173 130 169 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 185 110 Q 188 130 184 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 200 110 Q 203 130 199 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 215 110 Q 218 130 214 150" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 230 112 Q 233 130 229 148" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 245 114 Q 248 130 244 146" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 260 116 Q 263 130 259 144" stroke="#1E293B" stroke-width="2.2" stroke-linecap="round"/>
            <path d="M 275 118 Q 278 130 274 142" stroke="#1E293B" stroke-width="2" stroke-linecap="round"/>
            <!-- Sharp Snout with Teeth -->
            <path d="M 30 130 L 70 132" stroke="#0F172A" stroke-width="2"/>
            <circle cx="68" cy="120" r="6.5" fill="#CBD5E1"/>
            <circle cx="68" cy="120" r="4" fill="#0F172A"/>
            <circle cx="66" cy="118" r="1.5" fill="#FFFFFF"/>
            <path d="M 98 112 Q 110 130 98 148" fill="none" stroke="#334155" stroke-width="1.8"/>
            <path d="M 112 128 Q 155 132 185 138 Q 150 136 112 132 Z" fill="#1E293B"/>
        """
    },
    "lutjanus_malabaricus": {
        "title": "Kakap Merah (Snapper)",
        "scientific": "Lutjanus malabaricus",
        "family": "Lutjanidae · Demersal / Karang",
        "glow": "#EF4444",
        "svg_content": """
            <defs>
                <linearGradient id="kakapred" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#7F1D1D" />
                    <stop offset="35%" stop-color="#DC2626" />
                    <stop offset="70%" stop-color="#EF4444" />
                    <stop offset="90%" stop-color="#FCA5A5" />
                    <stop offset="100%" stop-color="#FFF1F2" />
                </linearGradient>
            </defs>
            <path d="M 325 130 Q 360 85 375 75 L 360 130 L 375 185 Q 360 175 325 130 Z" fill="#DC2626"/>
            <!-- Spiny Dorsal Fin -->
            <path d="M 125 88 Q 180 50 240 75 Q 260 85 275 105 Z" fill="#B91C1C" stroke="#7F1D1D" stroke-width="1.5"/>
            <path d="M 235 155 Q 260 175 285 160 Z" fill="#DC2626"/>
            <!-- Deep Compressed Body with Steep Head Profile -->
            <path d="M 45 135 Q 85 85 150 85 Q 240 85 325 130 Q 240 175 150 175 Q 85 175 45 135 Z" fill="url(#kakapred)"/>
            <!-- Distinct Head Profile & Large Mouth -->
            <path d="M 45 135 L 85 140" stroke="#7F1D1D" stroke-width="2.5"/>
            <!-- Golden Eye -->
            <circle cx="85" cy="115" r="9" fill="#FBBF24"/>
            <circle cx="85" cy="115" r="5" fill="#7F1D1D"/>
            <circle cx="82" cy="112" r="2" fill="#FFFFFF"/>
            <!-- Opercular Cover -->
            <path d="M 115 95 Q 132 130 115 165" fill="none" stroke="#7F1D1D" stroke-width="2"/>
            <!-- Pectoral Fin -->
            <path d="M 125 130 Q 175 136 215 146 Q 170 142 125 136 Z" fill="#EF4444" stroke="#B91C1C" stroke-width="1"/>
        """
    },
    "epinephelus_coioides": {
        "title": "Kerapu Lumpur (Grouper)",
        "scientific": "Epinephelus coioides",
        "family": "Serranidae · Karang & Muara",
        "glow": "#D97706",
        "svg_content": """
            <defs>
                <linearGradient id="kerapuback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#451A03" />
                    <stop offset="35%" stop-color="#78350F" />
                    <stop offset="65%" stop-color="#92400E" />
                    <stop offset="85%" stop-color="#D97706" />
                    <stop offset="100%" stop-color="#FEF3C7" />
                </linearGradient>
            </defs>
            <path d="M 320 130 Q 355 90 370 80 Q 365 130 370 180 Q 355 170 320 130 Z" fill="#78350F"/>
            <!-- Long Continuous Spiny & Soft Dorsal Fin -->
            <path d="M 120 92 Q 200 65 285 105 Z" fill="#78350F" stroke="#92400E" stroke-width="2"/>
            <path d="M 230 158 Q 260 178 285 158 Z" fill="#78350F"/>
            <!-- Robust Heavy-set Body with Bulky Lower Jaw -->
            <path d="M 40 135 Q 75 88 150 88 Q 240 88 320 130 Q 240 172 150 172 Q 75 172 40 135 Z" fill="url(#kerapuback)"/>
            <!-- Orange/Brown Spots Dotting Body (Signature of Orange-Spotted Grouper) -->
            <g fill="#D97706" opacity="0.9">
                <circle cx="100" cy="110" r="2.5"/><circle cx="115" cy="105" r="3"/><circle cx="130" cy="112" r="2.8"/>
                <circle cx="145" cy="104" r="3"/><circle cx="160" cy="115" r="3.2"/><circle cx="175" cy="106" r="2.8"/>
                <circle cx="190" cy="114" r="3"/><circle cx="205" cy="108" r="3"/><circle cx="220" cy="116" r="2.8"/>
                <circle cx="235" cy="110" r="3"/><circle cx="250" cy="118" r="2.8"/><circle cx="265" cy="115" r="3"/>
                <circle cx="110" cy="125" r="3"/><circle cx="125" cy="130" r="2.8"/><circle cx="140" cy="126" r="3"/>
                <circle cx="155" cy="132" r="3.2"/><circle cx="170" cy="126" r="2.8"/><circle cx="185" cy="134" r="3"/>
                <circle cx="200" cy="128" r="3"/><circle cx="215" cy="134" r="2.8"/><circle cx="230" cy="128" r="3"/>
                <circle cx="245" cy="134" r="2.8"/><circle cx="260" cy="130" r="3"/><circle cx="275" cy="126" r="2.8"/>
                <circle cx="120" cy="145" r="3"/><circle cx="135" cy="142" r="2.8"/><circle cx="150" cy="148" r="3"/>
                <circle cx="165" cy="144" r="3"/><circle cx="180" cy="150" r="2.8"/><circle cx="195" cy="145" r="3"/>
                <circle cx="210" cy="150" r="2.8"/><circle cx="225" cy="145" r="3"/><circle cx="240" cy="148" r="2.8"/>
            </g>
            <!-- Large Grouper Eye -->
            <circle cx="75" cy="116" r="8.5" fill="#D97706"/>
            <circle cx="75" cy="116" r="5" fill="#451A03"/>
            <circle cx="73" cy="114" r="2" fill="#FFFFFF"/>
            <!-- Bulky Jaw -->
            <path d="M 38 135 L 75 142" stroke="#451A03" stroke-width="2.5"/>
            <path d="M 105 100 Q 120 130 105 160" fill="none" stroke="#451A03" stroke-width="2"/>
            <path d="M 115 130 Q 160 136 195 145 Q 155 142 115 136 Z" fill="#78350F"/>
        """
    },
    "sardinella_lemuru": {
        "title": "Ikan Lemuru (Sardinella)",
        "scientific": "Sardinella lemuru",
        "family": "Clupeidae · Pelagis Kecil",
        "glow": "#0284C7",
        "svg_content": """
            <defs>
                <linearGradient id="lemuruback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#0369A1" />
                    <stop offset="30%" stop-color="#0284C7" />
                    <stop offset="60%" stop-color="#38BDF8" />
                    <stop offset="85%" stop-color="#E0F2FE" />
                    <stop offset="100%" stop-color="#FFFFFF" />
                </linearGradient>
            </defs>
            <path d="M 330 130 Q 360 90 375 78 Q 360 125 348 130 Q 360 135 375 182 Q 360 170 330 130 Z" fill="#0284C7"/>
            <path d="M 170 102 Q 195 82 220 102 Z" fill="#0284C7"/>
            <path d="M 50 130 Q 85 102 150 102 Q 240 102 330 130 Q 240 158 150 158 Q 85 158 50 130 Z" fill="url(#lemuruback)"/>
            <!-- Silvery Fine Body Markings -->
            <path d="M 110 114 Q 180 112 250 116 Q 290 120 315 124" fill="none" stroke="#0284C7" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="78" cy="120" r="7" fill="#FDE047"/>
            <circle cx="78" cy="120" r="4" fill="#0C4A6E"/>
            <circle cx="76" cy="118" r="1.5" fill="#FFFFFF"/>
            <path d="M 102 108 Q 112 130 102 152" fill="none" stroke="#0284C7" stroke-width="1.6"/>
            <path d="M 115 128 Q 155 132 185 136 Q 150 134 115 132 Z" fill="#0284C7"/>
        """
    },
    "coryphaena_hippurus": {
        "title": "Ikan Lemadang (Mahi-mahi)",
        "scientific": "Coryphaena hippurus",
        "family": "Coryphaenidae · Pelagis Terbuka",
        "glow": "#22C55E",
        "svg_content": """
            <defs>
                <linearGradient id="mahiback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#065F46" />
                    <stop offset="25%" stop-color="#059669" />
                    <stop offset="50%" stop-color="#10B981" />
                    <stop offset="75%" stop-color="#FACC15" />
                    <stop offset="100%" stop-color="#FEF08A" />
                </linearGradient>
            </defs>
            <!-- Large Deeply Forked Tail -->
            <path d="M 335 130 Q 370 65 390 50 Q 365 125 350 130 Q 365 135 390 210 Q 370 195 335 130 Z" fill="#FACC15" stroke="#EAB308" stroke-width="1.5"/>
            <!-- Characteristic High Long Dorsal Fin running from Head to Tail -->
            <path d="M 75 72 Q 180 50 325 120 Q 240 75 75 72 Z" fill="#0284C7" stroke="#38BDF8" stroke-width="1.5"/>
            <!-- Angular Blunt Forehead of Bull Mahi-mahi -->
            <path d="M 50 135 L 50 85 Q 75 70 150 78 Q 250 85 335 130 Q 250 165 150 165 Q 85 165 50 135 Z" fill="url(#mahiback)"/>
            <!-- Iridescent Blue Spots on Golden Flanks -->
            <g fill="#0284C7">
                <circle cx="110" cy="100" r="2.5"/><circle cx="130" cy="95" r="2.5"/><circle cx="150" cy="98" r="2.5"/><circle cx="170" cy="96" r="2.5"/><circle cx="190" cy="100" r="2.5"/><circle cx="210" cy="102" r="2.5"/><circle cx="230" cy="108" r="2.5"/>
                <circle cx="120" cy="115" r="2.5"/><circle cx="140" cy="112" r="2.5"/><circle cx="160" cy="116" r="2.5"/><circle cx="180" cy="114" r="2.5"/><circle cx="200" cy="118" r="2.5"/><circle cx="220" cy="120" r="2.5"/><circle cx="240" cy="124" r="2.5"/>
            </g>
            <!-- Brilliant Gold & Green Eye -->
            <circle cx="75" cy="105" r="7.5" fill="#FACC15"/>
            <circle cx="75" cy="105" r="4.5" fill="#064E3B"/>
            <circle cx="73" cy="103" r="1.5" fill="#FFFFFF"/>
            <path d="M 50 135 L 75 136" stroke="#064E3B" stroke-width="2"/>
            <path d="M 100 88 Q 115 120 100 150" fill="none" stroke="#064E3B" stroke-width="1.8"/>
            <path d="M 115 125 Q 165 130 195 138 Q 155 136 115 132 Z" fill="#0284C7"/>
        """
    },
    "cheilinus_undulatus": {
        "title": "Ikan Napoleon (Humphead)",
        "scientific": "Cheilinus undulatus",
        "family": "Labridae · Karang Dilindungi",
        "glow": "#14B8A6",
        "svg_content": """
            <defs>
                <linearGradient id="napoleonback" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#0F766E" />
                    <stop offset="35%" stop-color="#0D9488" />
                    <stop offset="65%" stop-color="#14B8A6" />
                    <stop offset="85%" stop-color="#5EEAD4" />
                    <stop offset="100%" stop-color="#CCFBF1" />
                </linearGradient>
            </defs>
            <path d="M 315 130 Q 350 88 368 78 L 360 130 L 368 182 Q 350 172 315 130 Z" fill="#0F766E" stroke="#14B8A6" stroke-width="2"/>
            <path d="M 130 82 Q 210 60 280 102 Z" fill="#0F766E"/>
            <path d="M 225 160 Q 255 178 280 160 Z" fill="#0F766E"/>
            <!-- Massive Hump on Forehead & Thick Body -->
            <path d="M 45 138 Q 40 100 70 78 Q 100 68 150 78 Q 240 85 315 130 Q 240 175 150 175 Q 85 175 45 138 Z" fill="url(#napoleonback)"/>
            <!-- Fine Maze-like Facial Lines -->
            <path d="M 65 98 Q 75 92 85 96 Q 95 90 105 95" fill="none" stroke="#042F2E" stroke-width="1.8"/>
            <path d="M 68 106 Q 80 100 90 104 Q 100 98 110 103" fill="none" stroke="#042F2E" stroke-width="1.8"/>
            <path d="M 72 114 Q 85 108 96 112 Q 106 106 116 111" fill="none" stroke="#042F2E" stroke-width="1.8"/>
            <!-- Thick Fleshy Lips -->
            <path d="M 45 138 Q 58 135 68 138" stroke="#042F2E" stroke-width="3.5" stroke-linecap="round"/>
            <circle cx="85" cy="98" r="7.5" fill="#FACC15"/>
            <circle cx="85" cy="98" r="4.5" fill="#042F2E"/>
            <circle cx="83" cy="96" r="1.5" fill="#FFFFFF"/>
            <!-- Large Rounded Pectoral Fin -->
            <path d="M 120 128 Q 165 125 190 145 Q 150 155 120 142 Z" fill="#0D9488" stroke="#14B8A6" stroke-width="1.5"/>
        """
    },
    "penaeus_monodon": {
        "title": "Udang Windu (Tiger Prawn)",
        "scientific": "Penaeus monodon",
        "family": "Penaeidae · Krustasea Dasar",
        "glow": "#F97316",
        "svg_content": """
            <defs>
                <linearGradient id="prawnback" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#431407" />
                    <stop offset="35%" stop-color="#9A3412" />
                    <stop offset="65%" stop-color="#EA580C" />
                    <stop offset="85%" stop-color="#FDBA74" />
                    <stop offset="100%" stop-color="#FFF7ED" />
                </linearGradient>
            </defs>
            <!-- Long Antennae -->
            <path d="M 70 105 Q 40 40 10 20" fill="none" stroke="#EA580C" stroke-width="1.8" stroke-linecap="round"/>
            <path d="M 75 110 Q 30 70 5 60" fill="none" stroke="#EA580C" stroke-width="1.8" stroke-linecap="round"/>
            <path d="M 80 115 Q 35 120 15 130" fill="none" stroke="#EA580C" stroke-width="1.8" stroke-linecap="round"/>
            <!-- Head Carapace with Rostrum (Gerigi tanduk kepala) -->
            <path d="M 50 115 L 75 105 L 140 105 L 135 145 L 85 145 Z" fill="url(#prawnback)"/>
            <!-- Rostral Teeth -->
            <path d="M 55 113 L 58 108 L 63 111 L 66 106 L 71 109 L 74 104" stroke="#431407" stroke-width="1.8"/>
            <!-- Segmented Curved Abdomen with Tiger Stripes -->
            <!-- Segment 1 -->
            <path d="M 135 105 Q 165 108 175 115 L 170 152 Q 145 148 135 145 Z" fill="#EA580C" stroke="#431407" stroke-width="2"/>
            <path d="M 148 106 L 142 147" stroke="#431407" stroke-width="3"/>
            <!-- Segment 2 -->
            <path d="M 172 113 Q 200 120 215 130 L 205 162 Q 185 156 168 152 Z" fill="#F97316" stroke="#431407" stroke-width="2"/>
            <path d="M 188 118 L 180 157" stroke="#431407" stroke-width="3"/>
            <!-- Segment 3 -->
            <path d="M 212 128 Q 240 138 255 152 L 240 178 Q 220 168 202 162 Z" fill="#EA580C" stroke="#431407" stroke-width="2"/>
            <path d="M 230 135 L 218 172" stroke="#431407" stroke-width="3"/>
            <!-- Segment 4 -->
            <path d="M 252 150 Q 275 165 290 182 L 272 198 Q 255 186 238 178 Z" fill="#F97316" stroke="#431407" stroke-width="2"/>
            <path d="M 268 160 L 252 190" stroke="#431407" stroke-width="3"/>
            <!-- Tail Fan (Uropods & Telson) -->
            <path d="M 288 180 Q 330 195 350 205 Q 320 215 270 198 Z" fill="#C2410C" stroke="#431407" stroke-width="1.5"/>
            <path d="M 285 182 Q 335 210 345 228 Q 310 220 270 198 Z" fill="#EA580C" stroke="#431407" stroke-width="1.5"/>
            <!-- Walking Legs (Pereiopods) & Swimmerets (Pleopods) -->
            <path d="M 95 145 L 85 175 L 75 185" stroke="#EA580C" stroke-width="2" fill="none"/>
            <path d="M 110 145 L 102 178 L 92 188" stroke="#EA580C" stroke-width="2" fill="none"/>
            <path d="M 125 145 L 120 178 L 110 188" stroke="#EA580C" stroke-width="2" fill="none"/>
            <path d="M 155 150 L 150 175" stroke="#F97316" stroke-width="2" fill="none"/>
            <path d="M 190 158 L 185 182" stroke="#F97316" stroke-width="2" fill="none"/>
            <path d="M 225 168 L 220 190" stroke="#F97316" stroke-width="2" fill="none"/>
            <!-- Eye on stalk -->
            <circle cx="82" cy="112" r="5" fill="#0C0A09"/>
            <circle cx="80" cy="110" r="1.5" fill="#FFFFFF"/>
        """
    }
}

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 260" width="100%" height="100%" style="background:#070d18; border-radius:10px; overflow:hidden;">
    <defs>
        <radialGradient id="oceanGlow_{key}" cx="50%" cy="50%" r="65%">
            <stop offset="0%" stop-color="{glow}" stop-opacity="0.18" />
            <stop offset="60%" stop-color="#0a1426" stop-opacity="0.85" />
            <stop offset="100%" stop-color="#050a14" stop-opacity="0.98" />
        </radialGradient>
        <pattern id="grid_{key}" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255, 255, 255, 0.03)" stroke-width="1" />
        </pattern>
        <filter id="softGlow_{key}" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
    </defs>

    <!-- Card Background -->
    <rect width="400" height="260" fill="url(#oceanGlow_{key})" />
    <rect width="400" height="260" fill="url(#grid_{key})" />

    <!-- Subtle Depth Ring -->
    <circle cx="200" cy="130" r="110" fill="none" stroke="{glow}" stroke-opacity="0.08" stroke-width="2" stroke-dasharray="4,6" />
    <circle cx="200" cy="130" r="70" fill="none" stroke="rgba(255,255,255,0.04)" stroke-width="1" />

    <!-- Species Illustration -->
    <g id="fish-art">
        {svg_content}
    </g>

    <!-- Bottom Metadata Ribbon inside Image -->
    <rect x="0" y="222" width="400" height="38" fill="rgba(6, 11, 22, 0.82)" />
    <line x1="0" y1="222" x2="400" y2="222" stroke="rgba(255,255,255,0.12)" stroke-width="1" />
    
    <!-- Title & Scientific Name -->
    <text x="14" y="238" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="11.5" font-weight="700" fill="#F8FAFC">{title}</text>
    <text x="14" y="251" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="9.5" font-style="italic" fill="#94A3B8">{scientific}</text>

    <!-- Badge Tag -->
    <rect x="270" y="231" width="116" height="18" rx="4" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.15)" stroke-width="1" />
    <text x="328" y="243.5" font-family="'Plus Jakarta Sans', system-ui, sans-serif" font-size="9" font-weight="600" fill="{glow}" text-anchor="middle">{family}</text>
</svg>
"""

out_dir = "web/assets/species"
os.makedirs(out_dir, exist_ok=True)

for key, data in SPECIES_DATA.items():
    svg = TEMPLATE.format(
        key=key,
        glow=data["glow"],
        title=data["title"],
        scientific=data["scientific"],
        family=data["family"],
        svg_content=data["svg_content"].strip()
    )
    file_path = os.path.join(out_dir, f"{key}.svg")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated {file_path}")

print("All 13 species SVGs generated successfully.")
