'use client'

import { Sparkles, Calendar, Users, MapPin, ChevronRight } from 'lucide-react'
import { useState, useEffect } from 'react'

export default function Hero() {
  const [currentImage, setCurrentImage] = useState(0)
  
  const images = [
    { label: 'Piscina principal com área segura' },
    { label: 'Churrasqueira e área gourmet' },
    { label: 'Espaço kids com pula-pula' },
    { label: 'Área coberta para eventos' },
  ]

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentImage((prev) => (prev + 1) % images.length)
    }, 4000)
    return () => clearInterval(interval)
  }, [])

  const features = [
    { icon: '🏊', label: 'Piscina adulto/infantil' },
    { icon: '🔥', label: 'Churrasqueira completa' },
    { icon: '🎪', label: 'Pula-pula e espaço kids' },
    { icon: '🎵', label: 'Som e Wi-Fi' },
    { icon: '🚿', label: '2 Banheiros completos' },
    { icon: '🏠', label: 'Área coberta/descoberta' },
  ]

  return (
    <section id="home" className="section pt-8 md:pt-12">
      <div className="container-custom px-4 sm:px-6 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Left Column - Content */}
          <div className="space-y-8">
            {/* Badge */}
            <div className="inline-flex items-center space-x-2 bg-primary-50 text-primary-700 px-4 py-2 rounded-full">
              <Sparkles size={16} />
              <span className="text-sm font-semibold">Espaço mais completo da região</span>
            </div>

            {/* Main Headline */}
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-gray-900 leading-tight font-display">
              <span className="block">DF Festas</span>
              <span className="block text-primary-600 mt-2">Sua festa,</span>
              <span className="block text-primary-600">nossa estrutura</span>
            </h1>

            {/* Description */}
            <p className="text-xl text-gray-600 max-w-2xl">
              Piscina, churrasqueira, pula-pula, som, Wi-Fi, área coberta e descoberta. 
              Tudo pronto para aniversários, confraternizações e eventos em <span className="font-semibold">Rio de Janeiro – RJ</span>.
            </p>

            {/* Features Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {features.map((feature, index) => (
                <div key={index} className="flex items-center space-x-3 bg-white p-3 rounded-lg shadow-sm border border-gray-100">
                  <span className="text-2xl">{feature.icon}</span>
                  <span className="text-sm font-medium text-gray-700">{feature.label}</span>
                </div>
              ))}
            </div>

            {/* Location and Capacity */}
            <div className="flex flex-wrap gap-6">
              <div className="flex items-center space-x-2">
                <MapPin className="text-primary-600" size={20} />
                <div>
                  <p className="font-semibold text-gray-900">Rua Basílio de Brito</p>
                  <p className="text-sm text-gray-600">Cachambi, Rio de Janeiro</p>
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <Users className="text-primary-600" size={20} />
                <div>
                  <p className="font-semibold text-gray-900">Até 50 pessoas</p>
                  <p className="text-sm text-gray-600">Capacidade confortável</p>
                </div>
              </div>
            </div>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-4">
              <a
                href="#calendar"
                className="btn-primary inline-flex items-center justify-center space-x-2 text-lg"
              >
                <Calendar size={20} />
                <span>Ver agenda disponível</span>
                <ChevronRight size={20} />
              </a>
              <a
                href="https://wa.me/5521999999999?text=Olá! Gostaria de saber mais sobre o DF Festas"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-outline inline-flex items-center justify-center"
              >
                Falar com atendente
              </a>
            </div>

            {/* Trust Signals */}
            <div className="pt-4 border-t border-gray-100">
              <p className="text-sm text-gray-500">
                ✅ Reserva 100% segura • 📄 Contrato digital • 💰 Melhor custo-benefício
              </p>
            </div>
          </div>

          {/* Right Column - Image Slider */}
          <div className="relative">
            <div className="relative overflow-hidden rounded-2xl shadow-2xl">
              {/* Main Image */}
              <div className="relative h-96 md:h-[500px] bg-gradient-to-br from-primary-400 to-primary-600">
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-white text-center p-8">
                    <div className="text-8xl mb-4">
                      {currentImage === 0 && '🏊'}
                      {currentImage === 1 && '🔥'}
                      {currentImage === 2 && '🎪'}
                      {currentImage === 3 && '🏠'}
                    </div>
                    <h3 className="text-2xl font-bold mb-2">{images[currentImage].label}</h3>
                    <p className="text-primary-100">Toque para ver mais</p>
                  </div>
                </div>
              </div>

              {/* Image Dots */}
              <div className="absolute bottom-6 left-1/2 transform -translate-x-1/2 flex space-x-2">
                {images.map((_, index) => (
                  <button
                    key={index}
                    onClick={() => setCurrentImage(index)}
                    className={`w-2 h-2 rounded-full transition-all duration-300 ${
                      index === currentImage 
                        ? 'bg-white w-8' 
                        : 'bg-white/50 hover:bg-white/80'
                    }`}
                    aria-label={`Ver imagem ${index + 1}`}
                  />
                ))}
              </div>
            </div>

            {/* Floating Cards */}
            <div className="absolute -bottom-6 -left-6">
              <div className="bg-white p-4 rounded-xl shadow-lg border border-gray-100 animate-fade-in">
                <div className="flex items-center space-x-3">
                  <div className="bg-accent-100 text-accent-800 p-2 rounded-lg">
                    <Calendar size={20} />
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900">Reserva rápida</p>
                    <p className="text-sm text-gray-600">Via WhatsApp</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="absolute -top-6 -right-6">
              <div className="bg-white p-4 rounded-xl shadow-lg border border-gray-100 animate-fade-in">
                <div className="flex items-center space-x-3">
                  <div className="bg-primary-100 text-primary-800 p-2 rounded-lg">
                    <Users size={20} />
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900">+500 festas</p>
                    <p className="text-sm text-gray-600">Realizadas com sucesso</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}