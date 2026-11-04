# -*- coding: utf-8 -*-
"""
NEXA | SmartStorage 360 - Simulador Web y Generador de Presupuestos Escalables
Proyecto Design Thinking - Grado en Física (Universidad de Granada)
Optimización de Baterías de Uso Personal, Gestión de Excedentes Solares (Curtailment) y Eficiencia Residencial.
"""

from dataclasses import dataclass
from typing import Dict, List, Any
import datetime

# ==============================================================================
# 1. CONFIGURACIÓN CORPORATIVA NEXA Y CONSTANTES TÉCNICAS
# ==============================================================================
COLOR_AZUL_OSCURO = "#0a528a"  # Primario NEXA
COLOR_AZUL_CLARO  = "#24b7da"  # Secundario / Acentuado
COLOR_SALMON      = "#fd9c7d"  # Acento cálido / Avisos de vertidos
COLOR_AMARILLO    = "#ffd95c"  # Destacados / Energía solar
COLOR_BG_LIGHT    = "#f4f8fb"  # Fondo general
COLOR_TEXT_DARK   = "#1e293b"  # Texto principal

FACTOR_SOLAR_CCAA = {
    "Andalucía": 1.25,
    "Comunidad Valenciana": 1.15,
    "Madrid": 1.10,
    "Cataluña": 1.05,
    "Otras CCAA (Sur)": 1.18,
    "Otras CCAA (Norte)": 0.88,
}

# ==============================================================================
# 2. ESTIMADOR DE CONSUMOS DESDE FACTURA MENSUAL
# ==============================================================================
def estimar_consumos_desde_factura(
    gasto_luz_mes: float = 120.0,
    gasto_gas_mes: float = 60.0,
    precio_elec: float = 0.142,
    precio_gas: float = 0.088,
    tiene_termo_elec: bool = True,
    tiene_clima_elec: bool = True,
    tiene_ve: bool = False,
    num_personas: int = 3,
) -> Dict[str, float]:
    """
    Desglosa las facturas mensuales de electricidad y gas en consumos anuales (kWh/año),
    separando el término fijo estimado y clasificando las cargas desplazables al pico solar.
    """
    termino_fijo_luz = min(gasto_luz_mes * 0.25, 28.0)
    termino_fijo_gas = min(gasto_gas_mes * 0.20, 12.0) if gasto_gas_mes > 0 else 0.0

    gasto_var_luz_anual = max(0.0, (gasto_luz_mes - termino_fijo_luz) * 12.0)
    gasto_var_gas_anual = max(0.0, (gasto_gas_mes - termino_fijo_gas) * 12.0)

    kwh_elec_anual = gasto_var_luz_anual / max(0.05, precio_elec)
    kwh_gas_anual = (gasto_var_gas_anual / max(0.03, precio_gas)) if gasto_gas_mes > 0 else 0.0

    kwh_acs_elec = (num_personas * 480.0) if tiene_termo_elec else 0.0
    kwh_clima_elec = (kwh_elec_anual * 0.28) if tiene_clima_elec else 0.0
    kwh_ve_elec = 1800.0 if tiene_ve else 0.0
    kwh_electrodomesticos_desplazables = min(950.0, kwh_elec_anual * 0.18)

    kwh_desplazables = min(
        kwh_elec_anual * 0.78,
        kwh_acs_elec + kwh_clima_elec + kwh_ve_elec + kwh_electrodomesticos_desplazables,
    )

    return {
        "kwh_elec_anual": round(kwh_elec_anual, 1),
        "kwh_gas_anual": round(kwh_gas_anual, 1),
        "kwh_totales_anual": round(kwh_elec_anual + kwh_gas_anual, 1),
        "kwh_desplazables_anual": round(kwh_desplazables, 1),
        "gasto_anual_total_eur": round((gasto_luz_mes + gasto_gas_mes) * 12.0, 2),
    }


# ==============================================================================
# 3. MODELO FÍSICO Y ENERGÉTICO DE LA VIVIENDA (CLASE CASA)
# ==============================================================================
@dataclass
class Casa:
    tipo_vivienda: str = "Unifamiliar / Chalet / Adosado"
    m2: float = 100.0
    ccaa: str = "Andalucía"
    presupuesto: float = 4000.0
    gasto_mensual: float = 120.0
    horario: str = "Principalmente Tardes/Noches"
    obra: str = "Acceso Total a Tejado"

    # Equipamiento térmico y eléctrico (Preguntas de diagnóstico Fase 1 / Prototipo 1)
    termo_elec: bool = True
    clima_elec: bool = True
    caldera_gas: bool = False
    vehiculo_elec: bool = False

    # Parámetros fotovoltaicos y tarifarios
    tiene_placas: bool = True
    potencia_solar_kwp: float = 4.0
    precio_compra_kwh: float = 0.18
    precio_excedente_kwh: float = 0.05
    ded_pct: float = 40.0  # Deducción IRPF (20%, 40% o 60%)

    def factor_solar(self) -> float:
        return FACTOR_SOLAR_CCAA.get(self.ccaa, 1.0)

    def produccion_solar_anual_kwh(self) -> float:
        if not self.tiene_placas or self.potencia_solar_kwp <= 0:
            return 0.0
        return round(self.potencia_solar_kwp * 1350.0 * self.factor_solar(), 1)

    def consumo_anual_estimado_kwh(self) -> float:
        gasto_anual = self.gasto_mensual * 12.0
        fijo_anual = min(gasto_anual * 0.22, 320.0)
        return round(max(1800.0, (gasto_anual - fijo_anual) / max(0.08, self.precio_compra_kwh)), 1)

    def ratio_autoconsumo_base(self) -> float:
        if self.horario == "Todo el día / Teletrabajo":
            return 0.42
        elif self.horario == "Principalmente Mañanas":
            return 0.35
        return 0.25

    def balance_solar_inicial(self) -> Dict[str, float]:
        prod = self.produccion_solar_anual_kwh()
        cons = self.consumo_anual_estimado_kwh()
        ratio_dir = self.ratio_autoconsumo_base()
        autoconsumo_dir = min(cons * 0.65, prod * ratio_dir)
        excedente_total = max(0.0, prod - autoconsumo_dir)
        consumo_red_restante = max(0.0, cons - autoconsumo_dir)

        # En España (RD 244/2019) la liquidación es MENSUAL (no anual) y en horas centrales de primavera/verano
        # el precio mayorista OMIE cae cerca de 0 €/MWh. Entre abril y septiembre se supera el tope mensual
        # de consumo nocturno, regalando a la red entre el 42% y el 58% del excedente total sin Batería Virtual ni HEMS.
        fraccion_compensable_efectiva = 0.48 if self.horario != "Todo el día / Teletrabajo" else 0.58
        kwh_compensados = round(excedente_total * fraccion_compensable_efectiva, 1)
        kwh_regalados_red = round(max(0.0, excedente_total - kwh_compensados), 1)

        return {
            "produccion_anual_kwh": round(prod, 1),
            "consumo_anual_kwh": round(cons, 1),
            "autoconsumo_directo_kwh": round(autoconsumo_dir, 1),
            "excedente_total_kwh": round(excedente_total, 1),
            "kwh_compensados": round(kwh_compensados, 1),
            "kwh_regalados_curtailment": round(kwh_regalados_red, 1),
            "consumo_red_nocturno_kwh": round(consumo_red_restante, 1),
            "tasa_autoconsumo_pct": round((autoconsumo_dir / prod * 100.0) if prod > 0 else 0.0, 1),
        }


# ==============================================================================
# 4. CATÁLOGO DE MEDIDAS: 5 NIVELES SMARTSTORAGE 360 + REHABILITACIÓN NEXA
# ==============================================================================
def construir_catalogo_medidas(casa: Casa, kw_solar_adicional: float = 4.0) -> List[Dict[str, Any]]:
    bal = casa.balance_solar_inicial()
    excedente_disp = bal["excedente_total_kwh"] if casa.tiene_placas else (kw_solar_adicional * 1350.0 * casa.factor_solar() * 0.70)
    gasto_anual = casa.gasto_mensual * 12.0
    p_compra = casa.precio_compra_kwh
    p_exc = casa.precio_excedente_kwh
    spread_solar = max(0.10, p_compra - (p_exc * 0.5))

    catalogo = []

    # --- NIVEL 1: CAMBIO DE HÁBITOS (DESPLAZAMIENTO DE CARGAS) ---
    kwh_n1 = min(excedente_disp * 0.20, 650.0 if not casa.vehiculo_elec else 1100.0)
    ahorro_n1 = round(kwh_n1 * spread_solar, 2)
    catalogo.append({
        "id": "N1_HABITOS",
        "nivel": 1,
        "categoria": "SmartStorage Nivel 1",
        "nombre": "Nivel 1: Cambio de Hábitos y Desplazamiento de Cargas (11:00–16:00 h)",
        "coste": 0.0,
        "cuota_anual": 0.0,
        "kwh_recuperados": round(kwh_n1, 1),
        "ahorro": max(115.0, ahorro_n1),
        "certificados": "No requiere trámites. Configuración de temporizadores diferidos en lavadora, lavavajillas y secadora.",
        "instalacion": "Programación escalonada de electrodomésticos en ventana solar pico (11:00 a 16:00 h).",
        "prioridad": 1,
    })

    # --- NIVEL 2: INERCIA TÉRMICA BÁSICA (CASA Y TERMO COMO BATERÍA) ---
    if casa.termo_elec or casa.clima_elec:
        kwh_n2 = min(max(0.0, excedente_disp - kwh_n1) * 0.32, 950.0)
        ahorro_n2 = round(kwh_n2 * spread_solar, 2)
        catalogo.append({
            "id": "N2_INERCIA",
            "nivel": 2,
            "categoria": "SmartStorage Nivel 2",
            "nombre": "Nivel 2: Inercia Térmica (Programador Wi-Fi Carril DIN 16A para Termo/Clima)",
            "coste": 85.0,
            "cuota_anual": 0.0,
            "kwh_recuperados": round(kwh_n2, 1),
            "ahorro": max(170.0, ahorro_n2),
            "certificados": "Marcado CE en relé inteligente Wi-Fi de cuadro eléctrico (16A).",
            "instalacion": "Montaje en cuadro general (1 hora de electricista) y ajuste de consigna diurna a 60 °C en termo / pre-climatización.",
            "prioridad": 2,
        })

    # --- NIVEL 3: DOMÓTICA SOLAR Y SISTEMA HEMS ---
    if casa.termo_elec or casa.clima_elec or casa.vehiculo_elec:
        kwh_n3 = min(max(0.0, excedente_disp - kwh_n1) * 0.50, 1600.0)
        ahorro_n3 = round(kwh_n3 * spread_solar, 2)
        catalogo.append({
            "id": "N3_HEMS",
            "nivel": 3,
            "categoria": "SmartStorage Nivel 3",
            "nombre": "Nivel 3: Domótica Solar HEMS (Desviador Dinámico de Excedentes + Protocolo SG Ready)",
            "coste": 690.0,
            "cuota_anual": 0.0,
            "kwh_recuperados": round(kwh_n3, 1),
            "ahorro": max(290.0, ahorro_n3),
            "certificados": "Marcado CE + Compatibilidad inversor Modbus/RS485 y contacto libre de potencial SG Ready.",
            "instalacion": "Pinza amperimétrica toroidal en cabecera + regulador de potencia triac (0–3.000 W) hacia termo y aerotermia.",
            "prioridad": 3,
        })

    # --- NIVEL 4: BATERÍA VIRTUAL (MONEDERO SOLAR EN COMERCIALIZADORA) ---
    kwh_n4 = max(450.0, bal["kwh_regalados_curtailment"])
    ahorro_n4 = round(kwh_n4 * max(0.07, p_exc * 1.4) - 48.0, 2)
    catalogo.append({
        "id": "N4_BVIRTUAL",
        "nivel": 4,
        "categoria": "SmartStorage Nivel 4",
        "nombre": "Nivel 4: Batería Virtual / Monedero Solar (Compensación 100% Excedentes Estacionales)",
        "coste": 48.0,
        "cuota_anual": 48.0,
        "kwh_recuperados": round(kwh_n4, 1),
        "ahorro": max(210.0, ahorro_n4),
        "certificados": "Contrato de autoconsumo con compensación de excedentes acogido a RD 244/2019.",
        "instalacion": "100% digital sin obras. Acumula en euros los excedentes de verano para descontarlos en invierno o segunda vivienda.",
        "prioridad": 4,
    })

    # --- NIVEL 5: BATERÍA FÍSICA DE LITIO MODULAR (5 kWh LFP OPTIMIZADA) ---
    kwh_n5 = 1825.0
    ahorro_n5 = round(kwh_n5 * p_compra, 2)
    catalogo.append({
        "id": "N5_LITIO_5KWH",
        "nivel": 5,
        "categoria": "SmartStorage Nivel 5",
        "nombre": "Nivel 5: Batería Física de Litio Modular LFP (5 kWh con BMS Integrado)",
        "coste": 2650.0,
        "cuota_anual": 0.0,
        "kwh_recuperados": round(kwh_n5, 1),
        "ahorro": max(330.0, ahorro_n5),
        "certificados": "Actualización CIE (Boletín Eléctrico) + Certificado de acoplamiento CC/CA según ITC-BT-40.",
        "instalacion": "Módulo LFP de 5 kWh anclado a pared, protecciones CC y conexión al inversor híbrido (dimensionada al mínimo gracias a niveles 1–3).",
        "prioridad": 5,
    })

    # --- MEDIDAS COMPLEMENTARIAS NEXA ---
    if not casa.tiene_placas:
        if casa.obra == "Solo Balcón/Sin Obra" or casa.tipo_vivienda == "Piso de Alquiler":
            catalogo.append({
                "id": "NEXA_SOLAR_BALCON",
                "nivel": 0,
                "categoria": "Generación Solar NEXA",
                "nombre": "Kit Solar Balcón Plug&Play (Láminas Flexibles Full Black 800W)",
                "coste": 550.0,
                "cuota_anual": 0.0,
                "kwh_recuperados": round(850.0 * casa.factor_solar(), 1),
                "ahorro": round(135.0 * casa.factor_solar(), 2),
                "certificados": "Certificado CE + Microinversor anti-isla certificado REBT.",
                "instalacion": "Fijación en barandilla con bridas de acero inoxidable y conexión Schuko directa.",
                "prioridad": 0,
            })
        else:
            catalogo.append({
                "id": "NEXA_SOLAR_TEJADO",
                "nivel": 0,
                "categoria": "Generación Solar NEXA",
                "nombre": f"Instalación Fotovoltaica Autoconsumo Tejado ({kw_solar_adicional:.1f} kWp)",
                "coste": 3800.0,
                "cuota_anual": 0.0,
                "kwh_recuperados": round(2400.0 * casa.factor_solar(), 1),
                "ahorro": round(650.0 * casa.factor_solar(), 2),
                "certificados": "CIE (Boletín Eléctrico) + Declaración Responsable + Registro Industrial CCAA.",
                "instalacion": "Estructura coplanar en cubierta e inversor híbrido preparado para HEMS y batería.",
                "prioridad": 0,
            })

    coste_insuflado = max(600.0, casa.m2 * 12.0)
    catalogo.append({
        "id": "NEXA_INSUFLADO",
        "nivel": 6,
        "categoria": "Envolvente Térmica NEXA",
        "nombre": f"Aislamiento Térmico por Insuflado en Cámara ({int(casa.m2)} m² para retener calor solar)",
        "coste": coste_insuflado,
        "cuota_anual": 0.0,
        "kwh_recuperados": round(casa.consumo_anual_estimado_kwh() * 0.22, 1),
        "ahorro": round(gasto_anual * 0.22, 2),
        "certificados": "Certificado de Eficiencia Energética (CEE) pre y post-intervención (Habilita deducción IRPF 40%).",
        "instalacion": "Inyección de lana mineral/celulosa ecológica en cámara de aire en 1 día sin escombros.",
        "prioridad": 6,
    })

    return catalogo


# ==============================================================================
# 5. MOTOR DE ESTRATEGIAS Y PAQUETES DE PRESUPUESTO (PROTOTIPO 2)
# ==============================================================================
def _evaluar_paquete(
    casa: Casa,
    medidas_seleccionadas: List[Dict[str, Any]],
    nombre_paquete: str,
    descripcion_paquete: str,
    aplica_irpf: bool = True,
) -> Dict[str, Any]:
    bal = casa.balance_solar_inicial()
    gasto_anual = casa.gasto_mensual * 12.0

    coste_bruto = sum(m["coste"] for m in medidas_seleccionadas)
    ahorro_bruto = sum(m["ahorro"] for m in medidas_seleccionadas)
    kwh_recuperados = sum(m["kwh_recuperados"] for m in medidas_seleccionadas)

    ahorro_anual = round(min(ahorro_bruto, gasto_anual * 0.92), 2)
    kwh_excedente_aprovechado = round(min(bal["excedente_total_kwh"], kwh_recuperados), 1)
    kwh_vertidos_restantes = round(max(0.0, bal["kwh_regalados_curtailment"] - kwh_excedente_aprovechado), 1)

    nuevo_autoconsumo_kwh = min(bal["produccion_anual_kwh"], bal["autoconsumo_directo_kwh"] + kwh_excedente_aprovechado)
    nueva_tasa_autoconsumo = round(
        (nuevo_autoconsumo_kwh / bal["produccion_anual_kwh"] * 100.0) if bal["produccion_anual_kwh"] > 0 else 85.0,
        1,
    )

    ded_pct_efectiva = (casa.ded_pct / 100.0) if (aplica_irpf and coste_bruto >= 600.0) else 0.0
    deduccion_irpf = round(coste_bruto * ded_pct_efectiva, 2)
    coste_neto = round(coste_bruto - deduccion_irpf, 2)

    payback_bruto = round(coste_bruto / ahorro_anual, 2) if ahorro_anual > 0 else 0.0
    payback_neto = round(coste_neto / ahorro_anual, 2) if ahorro_anual > 0 else 0.0

    return {
        "nombre_paquete": nombre_paquete,
        "descripcion": descripcion_paquete,
        "medidas": medidas_seleccionadas,
        "coste_bruto": round(coste_bruto, 2),
        "deduccion_irpf": deduccion_irpf,
        "ded_pct_aplicado": round(ded_pct_efectiva * 100.0, 1),
        "coste_neto": coste_neto,
        "ahorro_anual": ahorro_anual,
        "reduccion_factura_pct": round((ahorro_anual / gasto_anual * 100.0) if gasto_anual > 0 else 0.0, 1),
        "payback_sin_ayudas": payback_bruto,
        "payback_con_ayudas": payback_neto,
        "kwh_excedente_aprovechado": kwh_excedente_aprovechado,
        "kwh_vertidos_antes": bal["kwh_regalados_curtailment"],
        "kwh_vertidos_despues": kwh_vertidos_restantes,
        "autoconsumo_pct_antes": bal["tasa_autoconsumo_pct"],
        "autoconsumo_pct_despues": nueva_tasa_autoconsumo,
    }


def estrategias(
    casa: Casa,
    presupuesto_max: float = 4000.0,
    kw_solar_ref: float = 4.0,
    pct_objetivo: float = 75.0,
) -> Dict[str, Dict[str, Any]]:
    catalogo = construir_catalogo_medidas(casa, kw_solar_ref)
    por_id = {m["id"]: m for m in catalogo}

    # 1. Estrategia Rápida (Mínima inversión: Niveles 1 + 2 + 4)
    med_rapida = [por_id[k] for k in ["N1_HABITOS", "N2_INERCIA", "N4_BVIRTUAL"] if k in por_id]
    esc_rapida = _evaluar_paquete(
        casa,
        med_rapida,
        "Paquete Express: Hábitos + Inercia Térmica + Batería Virtual (Niveles 1, 2 y 4)",
        "Ideal para empezar sin obras ni desembolsos altos: programa termo/electrodomésticos y guarda excedentes en monedero virtual.",
        aplica_irpf=False,
    )

    # 2. Estrategia Óptima SmartStorage Sin Litio (Niveles 1 + 2 + 3 + 4)
    med_sin_litio = [por_id[k] for k in ["N1_HABITOS", "N2_INERCIA", "N3_HEMS", "N4_BVIRTUAL"] if k in por_id]
    esc_sin_litio = _evaluar_paquete(
        casa,
        med_sin_litio,
        "Paquete Recomendado SmartStorage (Niveles 1 + 2 + 3 HEMS + 4 Batería Virtual)",
        "Automatiza el 100% del desvío solar a agua caliente y climatización (HEMS) y acumula el resto en Batería Virtual sin comprar litio.",
        aplica_irpf=True,
    )

    # 3. Estrategia Mayor Ahorro / Independencia Total dentro del presupuesto del usuario
    med_mayor = []
    acum = 0.0
    orden_preferencia = [
        "NEXA_SOLAR_BALCON",
        "NEXA_SOLAR_TEJADO",
        "N1_HABITOS",
        "N2_INERCIA",
        "N3_HEMS",
        "N4_BVIRTUAL",
        "N5_LITIO_5KWH",
        "NEXA_INSUFLADO",
    ]
    for clave in orden_preferencia:
        if clave in por_id:
            item = por_id[clave]
            if clave == "N2_INERCIA" and "N3_HEMS" in por_id and presupuesto_max >= 3400.0:
                continue
            if acum + item["coste"] <= max(presupuesto_max, 850.0):
                med_mayor.append(item)
                acum += item["coste"]

    esc_mayor = _evaluar_paquete(
        casa,
        med_mayor,
        "Paquete Independencia Total SmartStorage 360 (Adaptado a tu Presupuesto)",
        "Combina automatización HEMS, Batería Virtual y Batería Física de Litio reducida a 5 kWh (un 36% más barata que sobredimensionar a 10 kWh).",
        aplica_irpf=True,
    )

    # 4. Escenario de Control: Batería Tradicional de 10 kWh comprada a ciegas sin gestión de excedentes
    esc_tradicional = {
        "nombre_paquete": "Enfoque Tradicional: Batería Física Grande (10 kWh) sin Gestión HEMS",
        "descripcion": "Comprar una batería sobredimensionada sin desplazar cargas ni usar inercia térmica: en verano se llena a las 12:30 h y sigue vertiendo a la red.",
        "medidas": [{
            "nivel": 5,
            "categoria": "Enfoque Tradicional",
            "nombre": "Batería Física de Litio Sobredimensionada (10 kWh instalada sin HEMS)",
            "coste": 5200.0,
            "ahorro": 385.0,
            "kwh_recuperados": 2100.0,
            "certificados": "CIE + Legalización estándar.",
            "instalacion": "Instalación directa de acumulador de 10 kWh sin optimización térmica previa.",
        }],
        "coste_bruto": 5200.0,
        "deduccion_irpf": 0.0,
        "ded_pct_aplicado": 0.0,
        "coste_neto": 5200.0,
        "ahorro_anual": 385.0,
        "reduccion_factura_pct": round((385.0 / (casa.gasto_mensual * 12.0)) * 100.0, 1),
        "payback_sin_ayudas": 13.5,
        "payback_con_ayudas": 13.5,
        "kwh_excedente_aprovechado": 2100.0,
        "kwh_vertidos_antes": casa.balance_solar_inicial()["kwh_regalados_curtailment"],
        "kwh_vertidos_despues": 950.0,
        "autoconsumo_pct_antes": casa.balance_solar_inicial()["tasa_autoconsumo_pct"],
        "autoconsumo_pct_despues": 68.0,
    }

    return {
        "rapida": {"esc": esc_rapida},
        "optima_sin_litio": {"esc": esc_sin_litio},
        "mayor": {"esc": esc_mayor},
        "tradicional": {"esc": esc_tradicional},
    }


# ==============================================================================
# 6. GENERADORES DE ENTREGABLES (INFORME TXT Y PRESUPUESTO WEB HTML/PDF)
# ==============================================================================
def generar_informe_texto(
    casa: Casa,
    escenario: Dict[str, Any],
    ccaa: str = "Andalucía",
    perfil_usuario: str = "Autoconsumidor con placas (SmartStorage 360)",
) -> str:
    bal = casa.balance_solar_inicial()
    gasto_anual = casa.gasto_mensual * 12.0
    es_andalucia = (ccaa == "Andalucía")

    out = []
    out.append("==========================================================================")
    out.append("        NEXA • SMARTSTORAGE 360 - INFORME TÉCNICO Y PRESUPUESTO           ")
    out.append("==========================================================================")
    out.append(f"Perfil Diagnosticado : {perfil_usuario}")
    out.append(f"Vivienda             : {casa.tipo_vivienda} ({int(casa.m2)} m²) | Zona: {ccaa}")
    out.append(f"Horario en Vivienda  : {casa.horario}")
    out.append(f"Equipamiento Térmico : Termo Elec: {'Sí' if casa.termo_elec else 'No'} | Clima/Aerotermia: {'Sí' if casa.clima_elec else 'No'} | Gas: {'Sí' if casa.caldera_gas else 'No'} | VE: {'Sí' if casa.vehiculo_elec else 'No'}")
    out.append(f"Presupuesto Máximo   : {casa.presupuesto:,.2f} € | Gasto Energético Actual: {gasto_anual:,.2f} €/año")
    out.append("--------------------------------------------------------------------------")
    out.append("1. DIAGNÓSTICO DE EXCEDENTES SOLARES Y VERTIDOS (CURTAILMENT DOMÉSTICO)")
    out.append("--------------------------------------------------------------------------")
    out.append(f"  • Producción Solar Anual Estimada ({casa.potencia_solar_kwp:.1f} kWp) : {bal['produccion_anual_kwh']:,.1f} kWh/año")
    out.append(f"  • Autoconsumo Directo Inicial                 : {bal['autoconsumo_directo_kwh']:,.1f} kWh/año ({bal['tasa_autoconsumo_pct']:.1f}%)")
    out.append(f"  • Excedente Total en Horas Centrales (11-16h) : {bal['excedente_total_kwh']:,.1f} kWh/año")
    out.append(f"  • Energía Regalada a la Red (Sobre Tope Legal): {bal['kwh_regalados_curtailment']:,.1f} kWh/año (Valor 0 €)")
    out.append("")
    out.append("--------------------------------------------------------------------------")
    out.append(f"2. PRESUPUESTO ESCALONADO: {escenario['nombre_paquete'].upper()}")
    out.append("--------------------------------------------------------------------------")
    for i, m in enumerate(escenario["medidas"], 1):
        out.append(f"  [{i}] {m['nombre']}")
        out.append(f"      • Inversión Estimada       : {m['coste']:,.2f} €")
        out.append(f"      • Excedente Solar Absorbido: +{m.get('kwh_recuperados', 0.0):,.0f} kWh/año")
        out.append(f"      • Ahorro Anual Generado    : {m['ahorro']:,.2f} €/año")
        out.append(f"      • Normativa / Requisitos   : {m['certificados']}")
        out.append(f"      • Ejecución Técnica        : {m['instalacion']}")
        out.append("")

    out.append("--------------------------------------------------------------------------")
    out.append("3. RESUMEN FINANCIERO, RETORNO DE INVERSIÓN (PAYBACK) Y COMPARATIVA")
    out.append("--------------------------------------------------------------------------")
    out.append(f"  • INVERSIÓN BRUTA DEL PAQUETE SELECCIONADO : {escenario['coste_bruto']:,.2f} €")
    out.append(f"  • AHORRO ENERGÉTICO ANUAL ESTIMADO         : {escenario['ahorro_anual']:,.2f} €/año (-{escenario['reduccion_factura_pct']:.1f}% en factura)")
    out.append(f"  • NUEVA TASA DE APROVECHAMIENTO SOLAR      : {escenario['autoconsumo_pct_despues']:.1f}% (Vertidos reducidos a {escenario['kwh_vertidos_despues']:,.0f} kWh)")
    out.append(f"  • TIEMPO DE AMORTIZACIÓN (Sin Subvenciones): {escenario['payback_sin_ayudas']:.2f} años")
    out.append("")
    out.append(f"  • DEDUCCIÓN FISCAL IRPF ({escenario['ded_pct_aplicado']:.0f}%)              : -{escenario['deduccion_irpf']:,.2f} €")
    out.append(f"  • INVERSIÓN NETA REAL TRAS IRPF            : {escenario['coste_neto']:,.2f} €")
    out.append(f"  • PAYBACK NETO CON DEDUCCIÓN FISCAL        : {escenario['payback_con_ayudas']:.2f} años")
    out.append("  * Comparativa vs Batería Tradicional 10 kWh a ciegas (5.200 € | Payback 13,5 años):")
    ahorro_capex = max(0.0, 5200.0 - escenario["coste_bruto"])
    out.append(f"    -> Ahorras {ahorro_capex:,.2f} € en inversión inicial gracias a priorizar HEMS e inercia térmica.")
    out.append("")
    out.append("--------------------------------------------------------------------------")
    out.append("4. GUÍA DE SUBVENCIONES Y BONIFICACIONES FISCALES APLICABLES")
    out.append("--------------------------------------------------------------------------")
    if es_andalucia:
        out.append("  [+] AGENCIA ANDALUZA DE LA ENERGÍA (Programa INEA / Fondos FEDER Andalucía):")
        out.append("      - Subvención del 40% al 65% en sistemas de almacenamiento, HEMS y envolvente.")
        out.append("      - Bonificación adicional del 50% en el IBI municipal durante 3-5 años (según Ayuntamiento).")
    else:
        out.append("  [+] PROGRAMAS AUTONÓMICOS DE ALMACENAMIENTO Y REHABILITACIÓN (NextGen / IDAE):")
        out.append("      - Ayudas directas a la incorporación de baterías detrás del contador y gestión de demanda.")
    out.append("  [+] DEDUCCIÓN ESTATAL IRPF (Agencia Tributaria):")
    out.append("      - Deducción del 20%, 40% o 60% en la cuota íntegra del IRPF al reducir el consumo de energía primaria no renovable.")
    out.append("==========================================================================")
    out.append("       NEXA • Conectamos ideas, impulsamos tu ahorro energético           ")
    out.append("==========================================================================")
    return "\n".join(out)


def generar_presupuesto_html(
    casa: Casa,
    escenario: Dict[str, Any],
    ccaa: str = "Andalucía",
    perfil_usuario: str = "Autoconsumidor con placas (SmartStorage 360)",
) -> str:
    bal = casa.balance_solar_inicial()
    todas_est = estrategias(casa, casa.presupuesto)
    fecha_str = datetime.date.today().strftime("%d/%m/%Y")

    filas_medidas = ""
    for idx, m in enumerate(escenario["medidas"], 1):
        payback_m = (m["coste"] / m["ahorro"]) if m["ahorro"] > 0 else 0.0
        pb_str = "Inmediato (0 años)" if m["coste"] <= 50 else f"{payback_m:.1f} años"
        filas_medidas += f"""
        <tr>
            <td style="font-weight:700; color:{COLOR_AZUL_OSCURO};">{m.get('categoria', f'Nivel {idx}')}</td>
            <td>
                <strong>{m['nombre']}</strong><br>
                <span style="font-size:12px; color:#555;">🔧 {m['instalacion']}</span><br>
                <span style="font-size:11px; color:#0a528a;">📋 {m['certificados']}</span>
            </td>
            <td style="text-align:right; font-weight:600;">+{m.get('kwh_recuperados', 0):,.0f} kWh/año</td>
            <td style="text-align:right; font-weight:700; color:#0a528a;">{m['coste']:,.2f} €</td>
            <td style="text-align:right; font-weight:700; color:#16a34a;">{m['ahorro']:,.2f} €/año</td>
            <td style="text-align:center;"><span class="badge-payback">{pb_str}</span></td>
        </tr>
        """

    esc_sin_litio = todas_est["optima_sin_litio"]["esc"]
    esc_mayor = todas_est["mayor"]["esc"]
    esc_trad = todas_est["tradicional"]["esc"]

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Presupuesto Personalizado NEXA - SmartStorage 360</title>
    <style>
        body {{
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: {COLOR_BG_LIGHT};
            color: {COLOR_TEXT_DARK};
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1020px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 14px;
            box-shadow: 0 8px 28px rgba(10, 82, 138, 0.12);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, {COLOR_AZUL_OSCURO} 0%, #0d6efd 100%);
            color: white;
            padding: 28px 36px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 30px;
            letter-spacing: 1px;
        }}
        .header .tagline {{
            color: {COLOR_AMARILLO};
            font-style: italic;
            margin-top: 6px;
            font-size: 14px;
        }}
        .meta-box {{
            text-align: right;
            font-size: 13px;
            background: rgba(255,255,255,0.12);
            padding: 12px 18px;
            border-radius: 8px;
        }}
        .content {{
            padding: 30px 36px;
        }}
        .section-title {{
            color: {COLOR_AZUL_OSCURO};
            border-bottom: 2px solid {COLOR_AZUL_CLARO};
            padding-bottom: 6px;
            margin-top: 26px;
            margin-bottom: 16px;
            font-size: 18px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: {COLOR_BG_LIGHT};
            border-left: 5px solid {COLOR_AZUL_CLARO};
            padding: 14px 16px;
            border-radius: 8px;
        }}
        .kpi-card.warn {{
            border-left-color: {COLOR_SALMON};
        }}
        .kpi-card.gold {{
            border-left-color: {COLOR_AMARILLO};
        }}
        .kpi-label {{
            font-size: 12px;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 600;
        }}
        .kpi-value {{
            font-size: 22px;
            font-weight: 800;
            color: {COLOR_AZUL_OSCURO};
            margin-top: 4px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 22px;
            font-size: 13.5px;
        }}
        th {{
            background-color: {COLOR_AZUL_OSCURO};
            color: white;
            padding: 11px 12px;
            text-align: left;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}
        tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        .badge-payback {{
            background-color: {COLOR_AMARILLO};
            color: {COLOR_TEXT_DARK};
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 12px;
            display: inline-block;
        }}
        .summary-banner {{
            background: linear-gradient(90deg, #f0f9ff 0%, #e0f2fe 100%);
            border: 1px solid {COLOR_AZUL_CLARO};
            border-radius: 10px;
            padding: 20px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 18px;
        }}
        .btn-print {{
            background-color: {COLOR_AZUL_OSCURO};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 700;
            cursor: pointer;
            font-size: 14px;
        }}
        .btn-print:hover {{
            background-color: {COLOR_AZUL_CLARO};
        }}
        @media print {{
            .no-print {{ display: none !important; }}
            body {{ background: white; padding: 0; }}
            .container {{ box-shadow: none; }}
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>NEXA • SmartStorage 360</h1>
            <div class="tagline">Conectamos ideas, impulsamos tu ahorro energético | Presupuesto Escalable de Almacenamiento Personal</div>
        </div>
        <div class="meta-box">
            <strong>Fecha:</strong> {fecha_str}<br>
            <strong>Ubicación:</strong> {ccaa} ({int(casa.m2)} m²)<br>
            <strong>Perfil:</strong> {perfil_usuario}
        </div>
    </div>

    <div class="content">
        <div class="no-print" style="text-align:right; margin-bottom:10px;">
            <button class="btn-print" onclick="window.print()">🖨️ Imprimir / Guardar Presupuesto como PDF</button>
        </div>

        <h2 class="section-title">1. Diagnóstico Inicial de Excedentes y Curtailment Doméstico</h2>
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Producción Solar ({casa.potencia_solar_kwp:.1f} kWp)</div>
                <div class="kpi-value">{bal['produccion_anual_kwh']:,.0f} kWh/año</div>
            </div>
            <div class="kpi-card warn">
                <div class="kpi-label">Excedente en Pico Solar (11–16h)</div>
                <div class="kpi-value" style="color:#d97706;">{bal['excedente_total_kwh']:,.0f} kWh/año</div>
            </div>
            <div class="kpi-card warn">
                <div class="kpi-label">Energía Regalada a Red (0 €)</div>
                <div class="kpi-value" style="color:#dc2626;">{bal['kwh_regalados_curtailment']:,.0f} kWh/año</div>
            </div>
            <div class="kpi-card gold">
                <div class="kpi-label">Aprovechamiento con NEXA</div>
                <div class="kpi-value" style="color:#16a34a;">{escenario['autoconsumo_pct_despues']:.1f}% Total</div>
            </div>
        </div>

        <h2 class="section-title">2. Desglose del Presupuesto Escalonado: {escenario['nombre_paquete']}</h2>
        <table>
            <thead>
                <tr>
                    <th style="width:14%;">Nivel</th>
                    <th style="width:42%;">Solución Técnica y Automatización</th>
                    <th style="width:13%; text-align:right;">Energía Recuperada</th>
                    <th style="width:11%; text-align:right;">Inversión</th>
                    <th style="width:11%; text-align:right;">Ahorro Anual</th>
                    <th style="width:9%; text-align:center;">Payback</th>
                </tr>
            </thead>
            <tbody>
                {filas_medidas}
            </tbody>
        </table>

        <div class="summary-banner">
            <div>
                <div style="font-size:15px; font-weight:700; color:{COLOR_AZUL_OSCURO};">RESUMEN ECONÓMICO DEL PROTOTIPO 2</div>
                <div style="font-size:13px; color:#334155; margin-top:4px;">
                    Inversión Bruta: <strong>{escenario['coste_bruto']:,.2f} €</strong> &nbsp;|&nbsp;
                    Deducción IRPF ({escenario['ded_pct_aplicado']:.0f}%): <strong style="color:#16a34a;">-{escenario['deduccion_irpf']:,.2f} €</strong> &nbsp;|&nbsp;
                    Ahorro Anual: <strong style="color:#16a34a;">{escenario['ahorro_anual']:,.2f} €/año</strong>
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:12px; text-transform:uppercase; color:#64748b; font-weight:700;">Coste Neto Final (Tras IRPF)</div>
                <div style="font-size:26px; font-weight:800; color:{COLOR_AZUL_OSCURO};">{escenario['coste_neto']:,.2f} €</div>
                <div style="font-size:12px; color:#16a34a; font-weight:700;">Amortización Neta: {escenario['payback_con_ayudas']:.1f} años</div>
            </div>
        </div>

        <h2 class="section-title">3. Comparativa de Decisión: ¿Por qué SmartStorage 360 supera a comprar Litio a ciegas?</h2>
        <table>
            <thead>
                <tr>
                    <th>Escenario / Estrategia</th>
                    <th style="text-align:right;">Inversión Bruta</th>
                    <th style="text-align:right;">Inversión Neta (IRPF)</th>
                    <th style="text-align:right;">Ahorro Anual</th>
                    <th style="text-align:center;">Retorno (Payback)</th>
                    <th>Veredicto Técnico</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Opción A: Paquete SmartStorage Sin Litio (Niveles 1+2+3+4)</strong></td>
                    <td style="text-align:right;">{esc_sin_litio['coste_bruto']:,.2f} €</td>
                    <td style="text-align:right; font-weight:700;">{esc_sin_litio['coste_neto']:,.2f} €</td>
                    <td style="text-align:right; color:#16a34a; font-weight:700;">{esc_sin_litio['ahorro_anual']:,.2f} €/año</td>
                    <td style="text-align:center;"><span class="badge-payback">{esc_sin_litio['payback_sin_ayudas']:.1f} años</span></td>
                    <td>Máxima rentabilidad: usa termo/aerotermia + HEMS + Batería Virtual.</td>
                </tr>
                <tr>
                    <td><strong>Opción B: Independencia Total (HEMS + Virtual + Litio 5 kWh)</strong></td>
                    <td style="text-align:right;">{esc_mayor['coste_bruto']:,.2f} €</td>
                    <td style="text-align:right; font-weight:700;">{esc_mayor['coste_neto']:,.2f} €</td>
                    <td style="text-align:right; color:#16a34a; font-weight:700;">{esc_mayor['ahorro_anual']:,.2f} €/año</td>
                    <td style="text-align:center;"><span class="badge-payback">{esc_mayor['payback_con_ayudas']:.1f} años</span></td>
                    <td>Reduce la batería de litio a la mitad (5 kWh) ahorrando un 36% de inversión.</td>
                </tr>
                <tr style="background-color:#fff1f2;">
                    <td><strong>Opción Tradicional: Batería Litio 10 kWh a ciegas (Sin HEMS)</strong></td>
                    <td style="text-align:right;">{esc_trad['coste_bruto']:,.2f} €</td>
                    <td style="text-align:right;">{esc_trad['coste_neto']:,.2f} €</td>
                    <td style="text-align:right;">{esc_trad['ahorro_anual']:,.2f} €/año</td>
                    <td style="text-align:center;"><span class="badge-payback" style="background:#fda4af;">{esc_trad['payback_sin_ayudas']:.1f} años</span></td>
                    <td>Sobredimensionada: se satura a mediodía en verano y tarda >13 años en amortizarse.</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
</body>
</html>"""
    return html


# 7. INTERFAZ WEB UNIFICADA (STREAMLIT)
def ejecutar_app_streamlit():
    import streamlit as st

    st.set_page_config(
        page_title="NEXA | SmartStorage 360 - Simulador y Presupuesto",
        page_icon="⚡",
        layout="wide",
    )

    st.markdown(
        f"""
        <style>
        .nexa-banner {{
            background: linear-gradient(135deg, {COLOR_AZUL_OSCURO} 0%, {COLOR_AZUL_CLARO} 100%);
            padding: 22px 28px;
            border-radius: 12px;
            color: white;
            margin-bottom: 20px;
        }}
        .nexa-banner h1 {{ margin: 0; font-size: 28px; color: white; }}
        .nexa-banner p {{ margin: 4px 0 0 0; color: {COLOR_AMARILLO}; font-style: italic; font-size: 15px; }}
        </style>
        <div class="nexa-banner">
            <h1>⚡ NEXA • SmartStorage 360</h1>
            <p>Conectamos ideas, impulsamos tu ahorro energético — Simulador de Baterías Personales y Gestión de Excedentes</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("🏠 1. Diagnóstico de tu Vivienda")
        tipo_viv = st.selectbox("Tipo de Vivienda", ["Unifamiliar / Chalet / Adosado", "Piso en Comunidad", "Piso de Alquiler"])
        m2 = st.slider("Superficie de la vivienda (m²)", 40, 350, 100, step=5)
        ccaa = st.selectbox("Comunidad Autónoma / Zona Climática", list(FACTOR_SOLAR_CCAA.keys()))
        horario = st.selectbox(
            "¿Pasas la mayor parte del día (11:00–16:00 h) dentro o fuera?",
            ["Principalmente Tardes/Noches", "Todo el día / Teletrabajo", "Principalmente Mañanas"],
        )

        st.header("🔥 2. Equipamiento Térmico y Cargas")
        termo_elec = st.checkbox("Termo eléctrico de agua caliente (ACS)", value=True)
        clima_elec = st.checkbox("Aerotermia / Suelo radiante / Bomba de calor", value=True)
        caldera_gas = st.checkbox("Calefacción por Caldera de Gas", value=False)
        vehiculo_elec = st.checkbox("Vehículo Eléctrico / Híbrido Enchufable", value=False)

        st.header("☀️ 3. Instalación Solar y Presupuesto")
        tiene_placas = st.checkbox("Ya tengo paneles solares instalados", value=True)
        kwp = st.slider("Potencia solar (kWp)", 1.5, 10.0, 4.0, step=0.5)
        gasto_mes = st.slider("Factura energética mensual (€/mes)", 40, 400, 120, step=10)
        presupuesto = st.slider("Presupuesto máximo de inversión (€)", 100, 10000, 3500, step=100)
        ded_pct = st.selectbox("Tramo Deducción IRPF Rehabilitación Energética (%)", [0.0, 20.0, 40.0, 60.0], index=2)

    casa_usuario = Casa(
        tipo_vivienda=tipo_viv,
        m2=float(m2),
        ccaa=ccaa,
        presupuesto=float(presupuesto),
        gasto_mensual=float(gasto_mes),
        horario=horario,
        termo_elec=termo_elec,
        clima_elec=clima_elec,
        caldera_gas=caldera_gas,
        vehiculo_elec=vehiculo_elec,
        tiene_placas=tiene_placas,
        potencia_solar_kwp=float(kwp),
        ded_pct=float(ded_pct),
    )

    res_estrategias = estrategias(casa_usuario, float(presupuesto), float(kwp))
    bal = casa_usuario.balance_solar_inicial()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Producción Solar Anual", f"{bal['produccion_anual_kwh']:,.0f} kWh")
    col2.metric("Excedente Diurno (11-16h)", f"{bal['excedente_total_kwh']:,.0f} kWh")
    col3.metric("Energía Regalada (Curtailment)", f"{bal['kwh_regalados_curtailment']:,.0f} kWh", delta="-Pérdida 0 €", delta_color="inverse")
    col4.metric("Ahorro Anual con Plan NEXA", f"{res_estrategias['mayor']['esc']['ahorro_anual']:,.0f} €/año", delta=f"Payback {res_estrategias['mayor']['esc']['payback_con_ayudas']:.1f} años")

    tab1, tab2, tab3 = st.tabs([
        "📊 1. Presupuesto Escalonado (5 Niveles SmartStorage)",
        "⚖️ 2. Comparativa de Paquetes (Sin Litio vs Litio 5 kWh vs 10 kWh)",
        "📄 3. Informe Técnico y Descarga de Presupuesto (PDF/HTML y TXT)",
    ])

    with tab1:
        st.subheader("Configuración Recomendada según tus Electrodomésticos y Horarios")
        paquete_elegido = st.radio(
            "Selecciona la modalidad de presupuesto que deseas explorar:",
            ["optima_sin_litio", "mayor", "rapida"],
            format_func=lambda k: {
                "optima_sin_litio": "⭐ Paquete Recomendado Sin Litio (Niveles 1 + 2 + 3 HEMS + 4 Batería Virtual — Máximo ROI)",
                "mayor": "🔋 Paquete Independencia Total (Adaptado a tu presupuesto — Incluye Litio 5 kWh si procede)",
                "rapida": "⚡ Paquete Express Low-Cost (Niveles 1 + 2 + 4 — Inversión Mínima < 150 €)",
            }[k],
        )
        esc_activo = res_estrategias[paquete_elegido]["esc"]
        for m in esc_activo["medidas"]:
            with st.expander(f"✅ {m['nombre']} — Coste: {m['coste']:,.2f} € | Ahorro: {m['ahorro']:,.2f} €/año", expanded=True):
                st.write(f"**Energía solar recuperada:** +{m.get('kwh_recuperados', 0):,.0f} kWh/año")
                st.write(f"**Instalación técnica:** {m['instalacion']}")
                st.write(f"**Normativa y certificados:** {m['certificados']}")

    with tab2:
        st.subheader("Comparativa de los 3 Escenarios del Prototipo 2")
        st.table([
            {
                "Estrategia": res_estrategias["rapida"]["esc"]["nombre_paquete"],
                "Inversión Bruta": f"{res_estrategias['rapida']['esc']['coste_bruto']:,.2f} €",
                "Inversión Neta (con IRPF)": f"{res_estrategias['rapida']['esc']['coste_neto']:,.2f} €",
                "Ahorro Anual": f"{res_estrategias['rapida']['esc']['ahorro_anual']:,.2f} €/año",
                "Payback Neto": f"{res_estrategias['rapida']['esc']['payback_con_ayudas']:.1f} años",
            },
            {
                "Estrategia": res_estrategias["optima_sin_litio"]["esc"]["nombre_paquete"],
                "Inversión Bruta": f"{res_estrategias['optima_sin_litio']['esc']['coste_bruto']:,.2f} €",
                "Inversión Neta (con IRPF)": f"{res_estrategias['optima_sin_litio']['esc']['coste_neto']:,.2f} €",
                "Ahorro Anual": f"{res_estrategias['optima_sin_litio']['esc']['ahorro_anual']:,.2f} €/año",
                "Payback Neto": f"{res_estrategias['optima_sin_litio']['esc']['payback_con_ayudas']:.1f} años",
            },
            {
                "Estrategia": res_estrategias["mayor"]["esc"]["nombre_paquete"],
                "Inversión Bruta": f"{res_estrategias['mayor']['esc']['coste_bruto']:,.2f} €",
                "Inversión Neta (con IRPF)": f"{res_estrategias['mayor']['esc']['coste_neto']:,.2f} €",
                "Ahorro Anual": f"{res_estrategias['mayor']['esc']['ahorro_anual']:,.2f} €/año",
                "Payback Neto": f"{res_estrategias['mayor']['esc']['payback_con_ayudas']:.1f} años",
            },
            {
                "Estrategia": res_estrategias["tradicional"]["esc"]["nombre_paquete"],
                "Inversión Bruta": "5,200.00 €",
                "Inversión Neta (con IRPF)": "5,200.00 €",
                "Ahorro Anual": "385.00 €/año",
                "Payback Neto": "13.5 años",
            },
        ])

    with tab3:
        txt_out = generar_informe_texto(casa_usuario, esc_activo, ccaa)
        html_out = generar_presupuesto_html(casa_usuario, esc_activo, ccaa)
        st.download_button(
            "📥 Descargar Presupuesto Oficial en HTML (Imprimible a PDF)",
            data=html_out.encode("utf-8"),
            file_name="presupuesto_nexa_smartstorage360.html",
            mime="text/html",
        )
        st.download_button(
            "📥 Descargar Informe Técnico en TXT",
            data=txt_out.encode("utf-8"),
            file_name="informe_nexa_smartstorage360.txt",
            mime="text/plain",
        )
        st.code(txt_out, language="text")


if __name__ == "__main__":
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            ejecutar_app_streamlit()
        else:
            raise RuntimeError("Modo consola / Spyder")
    except Exception:
        c_demo = Casa(clima_elec=True, ded_pct=40.0)
        est_demo = estrategias(c_demo, c_demo.presupuesto, 5.0, 75.0)
        txt_demo = generar_informe_texto(c_demo, est_demo["mayor"]["esc"], "Andalucía", "Autoconsumidor con placas (SmartStorage 360)")
        html_demo = generar_presupuesto_html(c_demo, est_demo["mayor"]["esc"], "Andalucía", "Autoconsumidor con placas (SmartStorage 360)")
        with open("presupuesto_nexa_smartstorage360.html", "w", encoding="utf-8") as fh:
            fh.write(html_demo)
        print(txt_demo)
        print("\n[OK] Archivo 'presupuesto_nexa_smartstorage360.html' generado automáticamente en la carpeta actual.")
        print("Para abrir la interfaz web interactiva en Streamlit, ejecuta en la terminal: streamlit run smartstorage360_nexa.py")
