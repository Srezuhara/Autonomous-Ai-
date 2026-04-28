import React, { useState } from 'react';
import { motion, type Variants } from 'framer-motion';
import { SplineScene } from '@/components/ui/splite';
import { ShaderAnimation } from '@/components/ui/shader-animation';
import { Spotlight } from '@/components/ui/spotlight';
import { Card } from '@/components/ui/card';
import { 
  ArrowRight, 
  Play, 
  Zap, 
  CheckCircle2, 
  Clock, 
  TrendingUp,
  FileText,
  ChevronRight,
  Activity,
  Sparkles,
  Code,
  Terminal,
  Database,
  Server,
  BarChart3
} from 'lucide-react';

// Hero Section Component
const HeroSection: React.FC = () => {
  const fadeUpVariants: Variants = {
    hidden: { opacity: 0, y: 30 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.8,
        delay: 0.2 + i * 0.15,
        ease: [0.25, 0.4, 0.25, 1],
      },
    }),
  };

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden bg-gradient-to-br from-[#2C1810] via-[#3E2723] to-[#5D4037]">
      {/* Shader Animation Background */}
      <div className="absolute inset-0 opacity-30">
        <ShaderAnimation />
      </div>
      
      {/* Background Gradient Overlays */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#D2691E]/30 via-transparent to-[#FF8C42]/20 blur-3xl" />
      <Spotlight className="-top-40 left-0 md:left-60 md:-top-20" fill="#EFEBE9" />
      
      {/* Animated Background Shapes - Enhanced Vibrancy */}
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 0.35, scale: 1 }}
        transition={{ duration: 2, ease: "easeOut" }}
        className="absolute top-20 left-10 w-96 h-96 rounded-full bg-[#FF8C42] blur-3xl"
      />
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 0.25, scale: 1 }}
        transition={{ duration: 2, delay: 0.3, ease: "easeOut" }}
        className="absolute bottom-20 right-10 w-80 h-80 rounded-full bg-[#D2691E] blur-3xl"
      />

      {/* Content */}
      <div className="relative z-10 container mx-auto px-4 md:px-6 max-w-7xl">
        <div className="text-center">
          {/* Badge */}
          <motion.div
            custom={0}
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-[#EFEBE9]/10 border border-[#EFEBE9]/20 backdrop-blur-sm mb-8"
          >
            <Sparkles className="w-4 h-4 text-[#FFD700]" />
            <span className="text-sm text-[#FFE4B5] tracking-wide font-medium">9-Agent AI Pipeline</span>
          </motion.div>

          {/* Main Heading */}
          <motion.div custom={1} variants={fadeUpVariants} initial="hidden" animate="visible">
            <h1 className="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-bold mb-6 tracking-tight">
              <span className="bg-clip-text text-transparent bg-gradient-to-b from-[#FFE4B5] to-[#FFD700]">
                Build Full-Stack Apps
              </span>
              <br />
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-[#FF8C42] via-[#FFD700] to-[#FFE4B5]">
                From Text Prompts
              </span>
            </h1>
          </motion.div>

          {/* Subheading */}
          <motion.div custom={2} variants={fadeUpVariants} initial="hidden" animate="visible">
            <p className="text-lg sm:text-xl md:text-2xl text-[#FFE4B5]/90 mb-10 leading-relaxed max-w-3xl mx-auto">
              Autonomous 9-agent pipeline that generates, reviews, debugs, and packages complete applications in under 8 minutes.
            </p>
          </motion.div>

          {/* CTA Buttons */}
          <motion.div custom={3} variants={fadeUpVariants} initial="hidden" animate="visible">
            <div className="flex flex-col sm:flex-row gap-4 justify-center items-center mb-16">
              <button className="group px-8 py-4 bg-gradient-to-r from-[#FF8C42] to-[#FFD700] text-[#2C1810] font-semibold rounded-full shadow-xl hover:shadow-2xl hover:from-[#FFD700] hover:to-[#FF8C42] transition-all duration-300 flex items-center gap-2">
                Start Building
                <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </button>
              <button className="px-8 py-4 bg-[#FFE4B5]/10 backdrop-blur-sm text-[#FFE4B5] font-semibold rounded-full border-2 border-[#FF8C42]/50 hover:bg-[#FF8C42]/20 hover:border-[#FFD700] transition-all duration-300 flex items-center gap-2">
                <Play className="w-5 h-5" />
                View Demo
              </button>
            </div>
          </motion.div>

          {/* Stats */}
          <motion.div custom={4} variants={fadeUpVariants} initial="hidden" animate="visible">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-8 max-w-4xl mx-auto">
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-bold text-[#FFD700] mb-2">9</div>
                <div className="text-[#FFE4B5]/80 text-sm">AI Agents</div>
              </div>
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-bold text-[#FFD700] mb-2">18</div>
                <div className="text-[#FFE4B5]/80 text-sm">Endpoints</div>
              </div>
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-bold text-[#FFD700] mb-2">&lt;8min</div>
                <div className="text-[#FFE4B5]/80 text-sm">Avg Build</div>
              </div>
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-bold text-[#FFD700] mb-2">24/7</div>
                <div className="text-[#FFE4B5]/80 text-sm">Support</div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
};

// 3D Interactive Showcase Component
const InteractiveShowcase: React.FC = () => {
  return (
    <div className="py-20 bg-gradient-to-b from-[#2C1810] to-[#3E2723]">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <Card className="w-full h-[600px] bg-[#1a0f0a]/80 backdrop-blur-xl relative overflow-hidden border-[#FF8C42]/30">
          <Spotlight
            className="-top-40 left-0 md:left-60 md:-top-20"
            fill="#FFD700"
          />
          
          <div className="absolute inset-0 bg-gradient-to-br from-[#FF8C42]/20 via-transparent to-[#D2691E]/20" />
          
          <div className="flex h-full flex-col md:flex-row">
            {/* Left content */}
            <div className="flex-1 p-8 md:p-12 relative z-10 flex flex-col justify-center">
              <motion.div
                initial={{ opacity: 0, x: -30 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.8 }}
              >
                <h2 className="text-4xl md:text-6xl font-bold bg-clip-text text-transparent bg-gradient-to-b from-[#FFE4B5] to-[#FF8C42] mb-4">
                  Interactive 3D
                </h2>
                <h3 className="text-2xl md:text-3xl font-semibold text-[#FFD700] mb-6">
                  AI-Powered Development
                </h3>
                <p className="mt-4 text-[#FFE4B5]/90 text-lg max-w-lg leading-relaxed">
                  Experience the future of application development with our autonomous AI agents. 
                  Watch as your ideas transform into production-ready code in real-time with 
                  immersive 3D visualization and cutting-edge technology.
                </p>
                <div className="mt-8 flex gap-4">
                  <button className="px-6 py-3 bg-gradient-to-r from-[#FF8C42] to-[#FFD700] text-[#2C1810] font-semibold rounded-full hover:shadow-xl transition-all duration-300">
                    Explore Pipeline
                  </button>
                </div>
              </motion.div>
            </div>

            {/* Right content - 3D Scene */}
            <div className="flex-1 relative">
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 0.8, delay: 0.2 }}
                className="w-full h-full"
              >
                <SplineScene 
                  scene="https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode"
                  className="w-full h-full"
                />
              </motion.div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};

// Pipeline Visualizer Component
const PipelineVisualizer: React.FC = () => {
  const agents = [
    { name: 'Analyzer', icon: Activity },
    { name: 'Planner', icon: FileText },
    { name: 'Frontend', icon: Code },
    { name: 'Backend', icon: Server },
    { name: 'Reviewer', icon: CheckCircle2 },
    { name: 'Debugger', icon: Terminal },
    { name: 'Tester', icon: BarChart3 },
    { name: 'Packager', icon: Database },
  ];

  return (
    <div className="py-20 bg-gradient-to-b from-[#3E2723] to-[#2C1810]">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#FFE4B5] to-[#FFD700] mb-4">
            9-Agent Pipeline
          </h2>
          <p className="text-lg text-[#FFE4B5]/80 max-w-2xl mx-auto">
            Each agent specializes in a specific task, working together to deliver production-ready applications
          </p>
        </motion.div>

        <div className="relative">
          <div className="flex flex-wrap justify-center gap-4 md:gap-6">
            {agents.map((agent, index) => (
              <React.Fragment key={agent.name}>
                <motion.div
                  initial={{ opacity: 0, scale: 0.8 }}
                  whileInView={{ opacity: 1, scale: 1 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: index * 0.1 }}
                  className="flex flex-col items-center"
                >
                  <div className="w-20 h-20 md:w-24 md:h-24 rounded-2xl bg-gradient-to-br from-[#FF8C42]/20 to-[#D2691E]/20 backdrop-blur-sm border-2 border-[#FF8C42]/40 flex items-center justify-center mb-3 hover:bg-[#FF8C42]/30 hover:border-[#FFD700] hover:scale-110 transition-all duration-300 shadow-lg hover:shadow-[#FF8C42]/50">
                    <agent.icon className="w-8 h-8 md:w-10 md:h-10 text-[#FFD700]" />
                  </div>
                  <span className="text-sm font-medium text-[#FFE4B5]">{agent.name}</span>
                </motion.div>
                {index < agents.length - 1 && (
                  <div className="hidden md:flex items-center">
                    <ChevronRight className="w-6 h-6 text-[#FF8C42]" />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// Feature Cards Component
const FeatureCards: React.FC = () => {
  const features = [
    {
      icon: Activity,
      title: '9-Agent Pipeline',
      description: 'Autonomous multi-agent system that handles every aspect of application development from analysis to packaging.',
      gradient: 'from-[#FF8C42] to-[#D2691E]'
    },
    {
      icon: Zap,
      title: 'Groq Multi-Key Rotation',
      description: 'Intelligent API key management ensures uninterrupted service with automatic failover and load balancing.',
      gradient: 'from-[#FFD700] to-[#FF8C42]'
    },
    {
      icon: TrendingUp,
      title: 'Realtime Analytics',
      description: 'Live monitoring of build progress, resource usage, and performance metrics through WebSocket connections.',
      gradient: 'from-[#FFDEAD] to-[#FFD700]'
    }
  ];

  return (
    <div className="py-20 bg-gradient-to-b from-[#2C1810] to-[#3E2723]">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#FFE4B5] to-[#FFD700] mb-4">
            Core Features
          </h2>
          <p className="text-lg text-[#FFE4B5]/80 max-w-2xl mx-auto">
            Built with cutting-edge technology to deliver exceptional results
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {features.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: index * 0.2 }}
              className="group relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#1a0f0a]/80 to-[#2C1810]/60 backdrop-blur-sm border-2 border-[#FF8C42]/30 p-8 hover:border-[#FFD700] hover:shadow-2xl hover:shadow-[#FF8C42]/30 transition-all duration-300"
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${feature.gradient} opacity-0 group-hover:opacity-20 transition-opacity duration-300`} />
              <div className="relative z-10">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#FF8C42]/20 to-[#FFD700]/10 flex items-center justify-center mb-6 group-hover:scale-110 group-hover:shadow-lg group-hover:shadow-[#FFD700]/50 transition-all duration-300">
                  <feature.icon className="w-8 h-8 text-[#FFD700]" />
                </div>
                <h3 className="text-2xl font-bold text-[#FFE4B5] mb-4">{feature.title}</h3>
                <p className="text-[#FFE4B5]/80 leading-relaxed">{feature.description}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};

// FAQ Component
const FAQSection: React.FC = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const faqs = [
    {
      question: 'How long does it take to build an application?',
      answer: 'Our 9-agent pipeline typically completes a full-stack application in under 8 minutes, including code generation, review, debugging, testing, and packaging.'
    },
    {
      question: 'What types of applications can I build?',
      answer: 'You can build web apps, CLI tools, REST APIs, and data processing scripts. Our system supports multiple frameworks and languages based on your requirements.'
    },
    {
      question: 'How does the AI review process work?',
      answer: 'The Reviewer agent analyzes code quality, architecture, and best practices, providing scores from 0-10. The Debugger and Tester agents then validate functionality and performance.'
    },
    {
      question: 'Can I customize the generated code?',
      answer: 'Yes! You can download the complete source code, modify it as needed, and even trigger a rebuild with updated requirements through our dashboard.'
    },
    {
      question: 'What happens if a build fails?',
      answer: 'Our system provides detailed logs for each pipeline step. You can review the error, adjust your prompt, and retry the build with a single click.'
    }
  ];

  return (
    <div className="py-20 bg-gradient-to-b from-[#2C1810] to-[#3E2723]">
      <div className="container mx-auto px-4 md:px-6 max-w-4xl">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#FFE4B5] to-[#FFD700] mb-4">
            Frequently Asked Questions
          </h2>
          <p className="text-lg text-[#FFE4B5]/80">
            Everything you need to know about our AI App Builder
          </p>
        </motion.div>

        <div className="space-y-4">
          {faqs.map((faq, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: index * 0.1 }}
              className="rounded-2xl bg-gradient-to-br from-[#1a0f0a]/80 to-[#2C1810]/60 backdrop-blur-sm border-2 border-[#FF8C42]/30 overflow-hidden hover:border-[#FFD700] transition-all duration-300"
            >
              <button
                onClick={() => setOpenIndex(openIndex === index ? null : index)}
                className="w-full px-6 py-5 flex items-center justify-between text-left hover:bg-[#FF8C42]/10 transition-colors"
              >
                <span className="text-lg font-semibold text-[#FFE4B5]">{faq.question}</span>
                <ChevronRight
                  className={`w-5 h-5 text-[#FFD700] transition-transform duration-300 ${
                    openIndex === index ? 'rotate-90' : ''
                  }`}
                />
              </button>
              {openIndex === index && (
                <div className="px-6 pb-5">
                  <p className="text-[#FFE4B5]/80 leading-relaxed">{faq.answer}</p>
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};

// Contact Section Component
const ContactSection: React.FC = () => {
  return (
    <div className="py-20 bg-gradient-to-b from-[#3E2723] to-[#2C1810]">
      <div className="container mx-auto px-4 md:px-6 max-w-4xl">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center"
        >
          <h2 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#FFE4B5] to-[#FFD700] mb-6">
            Ready to Build Your App?
          </h2>
          <p className="text-lg text-[#FFE4B5]/80 mb-10 max-w-2xl mx-auto">
            Join thousands of developers using our AI-powered platform to bring their ideas to life
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center items-center">
            <button className="group px-8 py-4 bg-gradient-to-r from-[#FF8C42] to-[#FFD700] text-[#2C1810] font-semibold rounded-full shadow-xl hover:shadow-2xl hover:from-[#FFD700] hover:to-[#FF8C42] transition-all duration-300 flex items-center gap-2">
              Get Started Free
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
            <button className="px-8 py-4 bg-[#FFE4B5]/10 backdrop-blur-sm text-[#FFE4B5] font-semibold rounded-full border-2 border-[#FF8C42]/50 hover:bg-[#FF8C42]/20 hover:border-[#FFD700] transition-all duration-300">
              Contact Sales
            </button>
          </div>
        </motion.div>
      </div>
    </div>
  );
};

// Proof/Social Proof Component
const ProofSection: React.FC = () => {
  const stats = [
    { value: '150+', label: 'Projects Built', icon: CheckCircle2 },
    { value: '98%', label: 'Success Rate', icon: TrendingUp },
    { value: '7.5min', label: 'Avg Build Time', icon: Clock },
    { value: '24/7', label: 'Uptime', icon: Activity }
  ];

  return (
    <div className="py-20 bg-gradient-to-b from-[#3E2723] to-[#2C1810]">
      <div className="container mx-auto px-4 md:px-6 max-w-7xl">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#FFE4B5] to-[#FFD700] mb-4">
            Trusted by Developers Worldwide
          </h2>
          <p className="text-lg text-[#FFE4B5]/80 max-w-2xl mx-auto">
            Our platform delivers consistent results with industry-leading performance
          </p>
        </motion.div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((stat, index) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, scale: 0.8 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: index * 0.1 }}
              className="text-center p-8 rounded-3xl bg-gradient-to-br from-[#FF8C42]/10 to-[#D2691E]/5 backdrop-blur-sm border-2 border-[#FF8C42]/30 hover:border-[#FFD700] hover:shadow-xl hover:shadow-[#FF8C42]/30 transition-all duration-300"
            >
              <stat.icon className="w-12 h-12 text-[#FFD700] mx-auto mb-4" />
              <div className="text-4xl font-bold text-[#FFE4B5] mb-2">{stat.value}</div>
              <div className="text-[#FFE4B5]/70 text-sm">{stat.label}</div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};

// Main Landing Page Component
const Landing: React.FC = () => {
  return (
    <div className="w-full min-h-screen bg-gradient-to-b from-[#2C1810] via-[#3E2723] to-[#2C1810]">
      <HeroSection />
      <InteractiveShowcase />
      <PipelineVisualizer />
      <FeatureCards />
      <ProofSection />
      <FAQSection />
      <ContactSection />
    </div>
  );
};

export default Landing;
